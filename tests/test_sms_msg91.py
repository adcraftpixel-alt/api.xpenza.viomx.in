"""
Tests for MSG91 SMS delivery (app/utils/sms.py).

No network: httpx.post is patched. What matters is that we build the payload
MSG91's v5 Flow API expects and that business errors returned as HTTP 200 are
still treated as failures.
"""
import pytest

from app.config import settings
from app.utils import sms as sms_mod
from app.utils.sms import (
    SMSDeliveryError,
    SMSNotConfigured,
    _to_msg91_mobile,
    send_sms,
    sms_configured,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "MSG91_AUTH_KEY", "test-auth-key")
    monkeypatch.setattr(settings, "MSG91_TEMPLATE_ID", "tmpl_123")
    monkeypatch.setattr(settings, "MSG91_SENDER_ID", "RUPEXI")


@pytest.fixture
def captured(monkeypatch):
    """Capture the outgoing request instead of sending it."""
    calls = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        calls["url"] = url
        calls["json"] = json
        calls["headers"] = headers
        return _FakeResponse(200, {"type": "success", "request_id": "req-1"})

    monkeypatch.setattr(sms_mod.httpx, "post", fake_post)
    return calls


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+919876543210", "919876543210"),
        ("919876543210", "919876543210"),
        ("9876543210", "919876543210"),
        ("+91 98765-43210", "919876543210"),
    ],
)
def test_mobile_normalisation(raw, expected):
    assert _to_msg91_mobile(raw) == expected


def test_not_configured_without_template(monkeypatch):
    """An auth key alone is not enough — MSG91 rejects sends with no template."""
    monkeypatch.setattr(settings, "MSG91_AUTH_KEY", "key")
    monkeypatch.setattr(settings, "MSG91_TEMPLATE_ID", "")
    assert sms_configured() is False
    with pytest.raises(SMSNotConfigured):
        send_sms("+919876543210", "Rupexi OTP: 123456")


def test_payload_shape(configured, captured):
    request_id = send_sms("+919876543210", "Rupexi OTP: 123456. Valid for 5 minutes.")

    assert request_id == "req-1"
    assert captured["url"] == "https://control.msg91.com/api/v5/flow/"
    assert captured["headers"]["authkey"] == "test-auth-key"

    body = captured["json"]
    assert body["template_id"] == "tmpl_123"
    assert body["sender"] == "RUPEXI"
    assert body["recipients"] == [{"mobiles": "919876543210", "OTP": "123456"}]


def test_otp_extracted_from_body(configured, captured):
    """Existing callers pass a rendered string, not a separate otp argument."""
    send_sms("9876543210", "Rupexi password reset code: 998877. Valid for 1 hour.")
    assert captured["json"]["recipients"][0]["OTP"] == "998877"


def test_explicit_otp_wins(configured, captured):
    send_sms("9876543210", "ignore 111111 in text", otp="222222")
    assert captured["json"]["recipients"][0]["OTP"] == "222222"


def test_business_error_on_http_200_is_a_failure(configured, monkeypatch):
    """MSG91 returns 200 with type=error for a bad template or no credits."""
    monkeypatch.setattr(
        sms_mod.httpx, "post",
        lambda *a, **k: _FakeResponse(200, {"type": "error", "message": "template not found"}),
    )
    with pytest.raises(SMSDeliveryError, match="template not found"):
        send_sms("+919876543210", "Rupexi OTP: 123456")


def test_http_error_is_a_failure(configured, monkeypatch):
    monkeypatch.setattr(
        sms_mod.httpx, "post",
        lambda *a, **k: _FakeResponse(401, {"message": "authkey invalid"}),
    )
    with pytest.raises(SMSDeliveryError, match="authkey invalid"):
        send_sms("+919876543210", "Rupexi OTP: 123456")


def test_network_error_is_wrapped(configured, monkeypatch):
    def boom(*a, **k):
        raise sms_mod.httpx.ConnectError("connection refused")

    monkeypatch.setattr(sms_mod.httpx, "post", boom)
    with pytest.raises(SMSDeliveryError, match="MSG91 request failed"):
        send_sms("+919876543210", "Rupexi OTP: 123456")


def test_invalid_destination_rejected(configured, captured):
    with pytest.raises(SMSDeliveryError, match="Invalid destination"):
        send_sms("not-a-number", "Rupexi OTP: 123456")


# ---------------------------------------------------------------------------
# The MSG91 path makes /auth/verify-otp primary again, so it must reconcile
# legacy phone formats exactly like the Firebase path does.
# ---------------------------------------------------------------------------

def test_verify_otp_matches_legacy_bare_phone(client, db):
    """A pre-existing user stored as bare 10 digits must not be duplicated."""
    from app.models.user import User
    from app.api.v1.auth.service import AuthService, store_otp

    legacy = User(
        name="Legacy OTP User",
        phone="9876511111",          # old register-screen format
        is_verified=True,
        is_active=True,
        onboarding_done=True,
    )
    db.add(legacy)
    db.commit()
    legacy_id = str(legacy.id)

    # The app now always sends E.164.
    store_otp("+919876511111", "445566", 300, "login", db)
    tokens = AuthService().verify_otp(db, "+919876511111", "445566")

    assert tokens is not None
    assert tokens.user["id"] == legacy_id, "created a duplicate account"
    assert tokens.user["onboarding_done"] is True
    assert tokens.user["phone"] == "+919876511111"
    assert db.query(User).filter(User.phone == "9876511111").count() == 0


def test_verify_otp_rejects_bad_code(client, db):
    from app.api.v1.auth.service import AuthService, store_otp

    store_otp("+919876522222", "111111", 300, "login", db)
    assert AuthService().verify_otp(db, "+919876522222", "999999") is None
