"""
Tests for Firebase phone authentication (POST /auth/firebase-verify).

Firebase itself is never contacted: the Admin SDK's token verification is
patched, since what we actually need to prove is that a verified phone number
maps to exactly one user account regardless of the format it was stored in.
"""
import pytest

from app.api.v1.auth import service as auth_service
from app.api.v1.auth.service import normalize_phone, _phone_lookup_candidates
from app.models.user import User


ENDPOINT = "/api/v1/auth/firebase-verify"


class _FakeFirebaseAuth:
    """Stand-in for ``firebase_admin.auth`` returning a canned decoded token."""

    def __init__(self, claims):
        self._claims = claims

    def verify_id_token(self, token, app=None):
        if token == "bad-token":
            raise ValueError("Token signature verification failed")
        return self._claims


def _install_fake_admin_sdk(monkeypatch, verify_fn):
    """Put a stub ``firebase_admin`` in sys.modules.

    The real package is an optional runtime dependency and is not installed in
    the test environment, so ``from firebase_admin import auth`` has to be
    satisfied by a stand-in. Registering both the package and its ``auth``
    submodule covers either import style.
    """
    import sys
    import types

    auth_module = types.ModuleType("firebase_admin.auth")
    auth_module.verify_id_token = verify_fn

    admin_module = types.ModuleType("firebase_admin")
    admin_module.auth = auth_module
    admin_module._apps = {}

    monkeypatch.setitem(sys.modules, "firebase_admin", admin_module)
    monkeypatch.setitem(sys.modules, "firebase_admin.auth", auth_module)

    # Pretend the service account is configured.
    monkeypatch.setattr("app.utils.firebase.get_firebase_app", lambda: object())


@pytest.fixture
def firebase_phone(monkeypatch):
    """Patch the Admin SDK so verify_firebase_phone accepts a fake token.

    Returns a setter so each test picks the phone number Firebase 'verified'.
    """

    def _use(phone, uid="firebase-uid-123", extra=None):
        claims = {"phone_number": phone, "uid": uid}
        if extra:
            claims.update(extra)
        _install_fake_admin_sdk(monkeypatch, _FakeFirebaseAuth(claims).verify_id_token)

    return _use


# ---------------------------------------------------------------------------
# Phone normalisation — the login screen sent "+919…" while the register screen
# sent a bare "9…", so users.phone holds both shapes.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+919876543210", "+919876543210"),
        ("9876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("0091 98765 43210", "+919876543210"),
        ("+91 98765-43210", "+919876543210"),
        ("+14155552671", "+14155552671"),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_lookup_candidates_cover_legacy_formats():
    candidates = _phone_lookup_candidates("+919876543210")
    assert "+919876543210" in candidates   # login-screen format
    assert "9876543210" in candidates      # register-screen format
    assert "919876543210" in candidates    # no-plus variant


# ---------------------------------------------------------------------------
# Endpoint behaviour
# ---------------------------------------------------------------------------

def test_firebase_verify_creates_user_on_first_signin(client, db, firebase_phone):
    firebase_phone("+919876500001")

    response = client.post(ENDPOINT, json={"id_token": "good-token"})
    assert response.status_code == 200

    data = response.json()
    data = data.get("data", data)
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["phone"] == "+919876500001"
    assert data["user"]["is_verified"] is True

    user = db.query(User).filter(User.phone == "+919876500001").first()
    assert user is not None
    assert user.firebase_uid == "firebase-uid-123"


def test_firebase_verify_is_idempotent(client, db, firebase_phone):
    firebase_phone("+919876500002")

    first = client.post(ENDPOINT, json={"id_token": "good-token"})
    second = client.post(ENDPOINT, json={"id_token": "good-token"})
    assert first.status_code == 200
    assert second.status_code == 200

    # Signing in twice must not create a second account.
    count = db.query(User).filter(User.phone == "+919876500002").count()
    assert count == 1


def test_firebase_verify_matches_legacy_bare_phone(client, db, firebase_phone):
    """A user registered before this change has a bare 10-digit phone stored.

    Firebase reports E.164, so without normalisation they'd get a duplicate
    account and lose all their expenses.
    """
    legacy = User(
        name="Legacy User",
        phone="9876500003",  # register-screen format, no country code
        is_verified=True,
        is_active=True,
        onboarding_done=True,
    )
    db.add(legacy)
    db.commit()
    legacy_id = str(legacy.id)

    firebase_phone("+919876500003")
    response = client.post(ENDPOINT, json={"id_token": "good-token"})
    assert response.status_code == 200

    data = response.json()
    data = data.get("data", data)
    # Same account, not a new one.
    assert data["user"]["id"] == legacy_id
    assert data["user"]["onboarding_done"] is True

    # And the row is migrated to E.164 so the format converges.
    db.expire_all()
    assert db.query(User).filter(User.id == legacy.id).first().phone == "+919876500003"
    assert db.query(User).filter(User.phone == "9876500003").count() == 0


def test_firebase_verify_rejects_invalid_token(client, firebase_phone):
    firebase_phone("+919876500004")
    response = client.post(ENDPOINT, json={"id_token": "bad-token"})
    assert response.status_code == 401


def test_firebase_verify_rejects_non_phone_token(client, monkeypatch):
    """A valid Google/Apple token has no phone_number claim — refuse it here."""
    _install_fake_admin_sdk(
        monkeypatch,
        lambda token, app=None: {"uid": "some-uid", "email": "user@example.com"},
    )

    response = client.post(ENDPOINT, json={"id_token": "google-token"})
    assert response.status_code == 401


def test_firebase_verify_rejects_suspended_account(client, db, firebase_phone):
    suspended = User(
        name="Banned",
        phone="+919876500005",
        is_verified=True,
        is_active=False,
        onboarding_done=True,
    )
    db.add(suspended)
    db.commit()

    firebase_phone("+919876500005")
    response = client.post(ENDPOINT, json={"id_token": "good-token"})
    assert response.status_code == 401


def test_firebase_verify_unconfigured_returns_clear_error(client, monkeypatch):
    """No service account in the environment must not 500."""
    monkeypatch.setattr("app.utils.firebase.get_firebase_app", lambda: None)
    response = client.post(ENDPOINT, json={"id_token": "any-token"})
    assert response.status_code in (400, 422, 503)
    assert "id_token" not in response.text  # don't echo the token back
