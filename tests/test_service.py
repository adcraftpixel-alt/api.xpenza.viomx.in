"""Tests for the Control Hub service API (/api/v1/service/*, HMAC-signed)."""
import pytest

from app.config import settings
from app.core import signing

SERVICE_KEY = "hub-test-key"


@pytest.fixture
def service_headers():
    """Yields a callable producing fresh signed headers per call — the
    signing scheme's replay guard rejects reusing the same nonce twice, so a
    static header dict can't be reused across multiple requests in one test."""
    original = settings.SERVICE_API_KEY
    settings.SERVICE_API_KEY = SERVICE_KEY
    yield lambda: signing.signed_headers(SERVICE_KEY, b"")
    settings.SERVICE_API_KEY = original


def test_service_disabled_without_key(client):
    """With no SERVICE_API_KEY configured, the service API is disabled (403)."""
    settings.SERVICE_API_KEY = ""
    resp = client.get("/api/v1/service/stats")
    assert resp.status_code == 403


def test_service_rejects_bad_signature(client, service_headers):
    resp = client.get(
        "/api/v1/service/stats", headers=signing.signed_headers("wrong-secret", b"")
    )
    assert resp.status_code == 401


def test_service_stats(client, service_headers, registered_user):
    resp = client.get("/api/v1/service/stats", headers=service_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    for key in (
        "total_users",
        "active_users",
        "total_revenue",
        "payment_count",
        "active_subscriptions",
        "total_wallet_funding",
    ):
        assert key in data
    assert data["total_users"] >= 1


def test_service_users(client, service_headers, registered_user):
    resp = client.get("/api/v1/service/users?limit=10", headers=service_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] >= 1
    assert isinstance(data["items"], list)
    u = data["items"][0]
    for key in ("id", "email", "name", "plan", "is_active", "created_at"):
        assert key in u


def test_service_users_search(client, service_headers, registered_user):
    email = registered_user["data"]["email"]
    resp = client.get(
        f"/api/v1/service/users?search={email}", headers=service_headers()
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert any(i["email"] == email for i in items)


def test_service_payments_shape(client, service_headers):
    resp = client.get("/api/v1/service/payments", headers=service_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "items" in data and "total" in data
    assert isinstance(data["items"], list)


def test_service_payment_methods_shape(client, service_headers):
    resp = client.get("/api/v1/service/payment-methods", headers=service_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "mandates" in data
    assert "expense_methods" in data
    assert isinstance(data["mandates"], list)
    assert isinstance(data["expense_methods"], list)


def test_service_funding_shape(client, service_headers):
    resp = client.get("/api/v1/service/funding", headers=service_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "items" in data
    assert isinstance(data["items"], list)


def test_service_block_unblock(client, service_headers, registered_user, db):
    from app.models.user import User

    uid = registered_user["data"]["id"]
    r = client.post(f"/api/v1/service/users/{uid}/block", headers=service_headers())
    assert r.status_code == 200
    db.expire_all()
    assert db.query(User).filter(User.id == uid).first().is_active is False

    r = client.post(f"/api/v1/service/users/{uid}/unblock", headers=service_headers())
    assert r.status_code == 200
    db.expire_all()
    assert db.query(User).filter(User.id == uid).first().is_active is True


def test_service_block_requires_key(client, registered_user):
    settings.SERVICE_API_KEY = ""
    uid = registered_user["data"]["id"]
    r = client.post(f"/api/v1/service/users/{uid}/block")
    assert r.status_code == 403


def test_plan_caps_fallback_and_override(db):
    from app.core.plan_limits import get_plan_caps
    from app.models.billing import BillingPlan

    # No caps stored → built-in fallback.
    caps = get_plan_caps("Free", db)
    assert caps.get("monthly_expenses") == 50
    assert caps.get("ai_insights") is False

    # Hub-synced caps override the fallback.
    pro = db.query(BillingPlan).filter(BillingPlan.name == "Pro").first()
    pro.caps = {"ai_insights": True, "ocr_scans": 100, "monthly_expenses": -1}
    db.commit()
    caps = get_plan_caps("Pro", db)
    assert caps["ai_insights"] is True
    assert caps["ocr_scans"] == 100


def test_service_payments_reflects_history(client, service_headers, auth_headers, db):
    """A recorded Razorpay payment appears in the service payments feed."""
    import uuid
    from app.models.payment_history import PaymentHistory

    me = client.get("/api/v1/users/me", headers=auth_headers).json()["data"]
    db.add(
        PaymentHistory(
            id=str(uuid.uuid4()),
            user_id=me["id"],
            razorpay_payment_id="pay_service_feed_001",
            gateway="razorpay",
            amount=199.0,
            currency="INR",
            status="paid",
        )
    )
    db.commit()

    resp = client.get("/api/v1/service/payments?limit=100", headers=service_headers())
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    match = [i for i in items if i["payment_id"] == "pay_service_feed_001"]
    assert match, "recorded payment not surfaced in service feed"
    assert match[0]["gateway"] == "razorpay"
    assert match[0]["amount"] == 199.0
    assert match[0]["user_email"] == me["email"]
