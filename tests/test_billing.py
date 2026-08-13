"""
Tests for billing endpoints: plans, checkout, subscription, invoices, webhook.
"""
import json


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def test_get_plans(client):
    """GET /billing/plans returns 200 and a list."""
    response = client.get("/api/v1/billing/plans")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)


def test_get_plans_has_free(client):
    """Free plan must exist in the list with price 0."""
    response = client.get("/api/v1/billing/plans")
    assert response.status_code == 200
    plans = response.json()["data"]
    free_plans = [p for p in plans if p["name"] == "Free"]
    assert len(free_plans) >= 1, "Free plan not found in plans list"
    assert free_plans[0]["price_monthly"] == 0


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

def test_checkout_free_plan(client, auth_headers, db):
    """Checking out a free plan (no stripe price) activates it immediately."""
    from app.models.billing import BillingPlan

    # Find the Free plan id
    free_plan = db.query(BillingPlan).filter(BillingPlan.name == "Free").first()
    if not free_plan:
        # Seed it if it somehow doesn't exist in test DB
        from app.models.billing import BillingPlan
        free_plan = BillingPlan(name="Free", price_monthly=0, price_yearly=0, is_active=True)
        db.add(free_plan)
        db.commit()
        db.refresh(free_plan)

    response = client.post(
        "/api/v1/billing/checkout",
        json={"plan_id": str(free_plan.id), "interval": "monthly"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    # Free plan activates immediately — no client_secret needed for payment
    assert data.get("activated") is True
    assert data.get("client_secret") is None


def test_checkout_nonexistent_plan(client, auth_headers):
    """Checking out a non-existent plan returns an error response."""
    response = client.post(
        "/api/v1/billing/checkout",
        json={"plan_id": "00000000-0000-0000-0000-000000000000", "interval": "monthly"},
        headers=auth_headers,
    )
    # Should return 4xx or success=False
    body = response.json()
    if response.status_code == 200:
        assert body.get("success") is False
    else:
        assert response.status_code in (400, 404, 422, 500)


def test_checkout_requires_auth(client, db):
    """Checkout without auth token returns 401."""
    from app.models.billing import BillingPlan
    free_plan = db.query(BillingPlan).filter(BillingPlan.name == "Free").first()
    if not free_plan:
        return  # Skip if no plans seeded

    response = client.post(
        "/api/v1/billing/checkout",
        json={"plan_id": str(free_plan.id), "interval": "monthly"},
    )
    assert response.status_code == 401


def test_checkout_paid_plan_mock(client, auth_headers, db):
    """Checking out a paid plan (no real Stripe key) returns mock client_secret."""
    from app.models.billing import BillingPlan

    # Find or create a Pro plan with a mock price_id so checkout triggers payment intent
    pro_plan = db.query(BillingPlan).filter(BillingPlan.name == "Pro").first()
    if not pro_plan:
        return  # Skip if not seeded

    # Temporarily set a fake price id so it triggers the payment intent path
    original_price_id = pro_plan.stripe_price_id_monthly
    pro_plan.stripe_price_id_monthly = "price_mock_test_pro"
    db.commit()

    try:
        response = client.post(
            "/api/v1/billing/checkout",
            json={"plan_id": str(pro_plan.id), "interval": "monthly"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        # In mock mode, we get a mock client_secret back
        data = body["data"]
        assert "client_secret" in data
    finally:
        # Restore
        pro_plan.stripe_price_id_monthly = original_price_id
        db.commit()


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

def test_get_subscription_default(client, auth_headers):
    """GET /billing/subscription returns plan info (default Free if none)."""
    response = client.get("/api/v1/billing/subscription", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert "plan" in data
    assert "status" in data
    assert data["status"] == "active"


def test_get_subscription_requires_auth(client):
    """GET /billing/subscription without token returns 401."""
    response = client.get("/api/v1/billing/subscription")
    assert response.status_code == 401


def test_subscription_reflects_free_plan_activation(client, auth_headers, db):
    """After activating free plan, subscription shows Free plan."""
    from app.models.billing import BillingPlan

    free_plan = db.query(BillingPlan).filter(BillingPlan.name == "Free").first()
    if not free_plan:
        return

    # Activate free plan
    client.post(
        "/api/v1/billing/checkout",
        json={"plan_id": str(free_plan.id), "interval": "monthly"},
        headers=auth_headers,
    )

    # Now check subscription
    response = client.get("/api/v1/billing/subscription", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["plan"] == "Free"
    assert data["status"] == "active"


# ---------------------------------------------------------------------------
# Cancel subscription
# ---------------------------------------------------------------------------

def test_cancel_subscription_no_sub(client, auth_headers):
    """DELETE /billing/subscription when no subscription returns graceful error."""
    response = client.delete("/api/v1/billing/subscription", headers=auth_headers)
    # Should return 4xx or success=False (not a 500)
    body = response.json()
    if response.status_code == 200:
        assert body.get("success") is False
    else:
        assert response.status_code in (400, 404, 422)


def test_cancel_subscription_after_activation(client, auth_headers, db):
    """Cancelling after activating Free plan sets cancel_at_period_end=True."""
    from app.models.billing import BillingPlan

    free_plan = db.query(BillingPlan).filter(BillingPlan.name == "Free").first()
    if not free_plan:
        return

    # First activate
    client.post(
        "/api/v1/billing/checkout",
        json={"plan_id": str(free_plan.id), "interval": "monthly"},
        headers=auth_headers,
    )

    # Then cancel
    response = client.delete("/api/v1/billing/subscription", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data.get("cancel_at_period_end") is True


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def test_get_invoices_empty(client, auth_headers):
    """GET /billing/invoices returns 200 with empty list when no invoices."""
    response = client.get("/api/v1/billing/invoices", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)


def test_get_invoices_requires_auth(client):
    """GET /billing/invoices without token returns 401."""
    response = client.get("/api/v1/billing/invoices")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

def test_webhook_subscription_created(client, db):
    """Webhook processes customer.subscription.created event."""
    # Register a user so we have a valid user_id
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Webhook User",
            "email": "webhookuser@example.com",
            "phone": "+919000009999",
            "password": "WebhookPass1!",
        },
    )
    assert reg_resp.status_code == 200
    user_id = reg_resp.json()["data"]["id"]

    from app.models.billing import BillingPlan
    # Create a plan with a stripe price id for webhook lookup
    plan = db.query(BillingPlan).filter(BillingPlan.name == "Pro").first()
    if not plan:
        return

    price_id = "price_webhook_test_123"
    original = plan.stripe_price_id_monthly
    plan.stripe_price_id_monthly = price_id
    db.commit()

    try:
        event_payload = {
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_webhook_test_001",
                    "status": "active",
                    "metadata": {"user_id": user_id},
                    "current_period_start": 1700000000,
                    "current_period_end": 1702678400,
                    "items": {
                        "data": [
                            {
                                "price": {"id": price_id}
                            }
                        ]
                    },
                }
            },
        }

        response = client.post(
            "/api/v1/billing/webhook",
            content=json.dumps(event_payload),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json().get("received") is True

        # Verify subscription was created in DB
        from app.models.billing import UserSubscription
        sub = db.query(UserSubscription).filter(
            UserSubscription.user_id == user_id
        ).first()
        assert sub is not None
        assert sub.stripe_subscription_id == "sub_webhook_test_001"
        assert sub.status == "active"
    finally:
        plan.stripe_price_id_monthly = original
        db.commit()


def test_webhook_subscription_updated(client, auth_headers, db):
    """Webhook processes customer.subscription.updated event."""
    from app.models.billing import BillingPlan, UserSubscription
    import uuid

    # Activate a plan first
    free_plan = db.query(BillingPlan).filter(BillingPlan.name == "Free").first()
    if not free_plan:
        return

    me = client.get("/api/v1/users/me", headers=auth_headers).json()["data"]
    user_id = me["id"]

    # Manually create subscription with a stripe sub id
    sub_id = "sub_update_test_001"
    existing = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()
    if existing:
        existing.stripe_subscription_id = sub_id
        existing.status = "active"
    else:
        sub = UserSubscription(
            id=str(uuid.uuid4()),
            user_id=user_id,
            plan_id=str(free_plan.id),
            stripe_subscription_id=sub_id,
            status="active",
        )
        db.add(sub)
    db.commit()

    event_payload = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": sub_id,
                "status": "active",
                "cancel_at_period_end": True,
            }
        },
    }

    response = client.post(
        "/api/v1/billing/webhook",
        content=json.dumps(event_payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json().get("received") is True

    # Verify cancel_at_period_end was updated
    db.expire_all()
    updated_sub = db.query(UserSubscription).filter(
        UserSubscription.stripe_subscription_id == sub_id
    ).first()
    assert updated_sub is not None
    assert updated_sub.cancel_at_period_end is True


def test_webhook_payment_succeeded(client, auth_headers, db):
    """Webhook processes invoice.payment_succeeded and records payment history."""
    from app.models.payment_history import PaymentHistory

    me = client.get("/api/v1/users/me", headers=auth_headers).json()["data"]
    user_id = me["id"]

    # Set a stripe_customer_id for the user
    from app.models.user import User
    user = db.query(User).filter(User.id == user_id).first()
    user.stripe_customer_id = "cus_test_payment_succeeded"
    db.commit()

    event_payload = {
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "id": "in_test_001",
                "customer": "cus_test_payment_succeeded",
                "amount_paid": 29900,
                "currency": "inr",
                "invoice_pdf": "https://stripe.com/invoice/in_test_001.pdf",
                "status_transitions": {"paid_at": 1700000000},
            }
        },
    }

    response = client.post(
        "/api/v1/billing/webhook",
        content=json.dumps(event_payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200

    # Check payment history was recorded
    db.expire_all()
    payment = db.query(PaymentHistory).filter(
        PaymentHistory.user_id == user_id,
        PaymentHistory.stripe_invoice_id == "in_test_001",
    ).first()
    assert payment is not None
    assert float(payment.amount) == 299.0
    assert payment.status == "paid"
    assert payment.currency == "INR"


def test_webhook_unknown_event_type(client):
    """Webhook with unknown event type responds with received=True without error."""
    event_payload = {
        "type": "unknown.event.type",
        "data": {"object": {}},
    }
    response = client.post(
        "/api/v1/billing/webhook",
        content=json.dumps(event_payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json().get("received") is True


# ---------------------------------------------------------------------------
# Razorpay: trial + ₹199/mo auto-pay mandate
# ---------------------------------------------------------------------------

def _pro_plan(db):
    from app.models.billing import BillingPlan
    return db.query(BillingPlan).filter(BillingPlan.name == "Pro").first()


def _mock_hub_create_subscription(monkeypatch):
    """create_razorpay_subscription now calls the Control Hub instead of
    Razorpay directly (the Hub holds the credentials) — mock that client call
    the same way test_plans_sync_from_hub_single_plan already mocks
    control_hub.fetch_plans, so these tests exercise our own state machine
    without needing real Hub/Razorpay credentials. Keeps the `sub_mock_*`
    naming so existing assertions (`startswith("sub_mock")`) still read true
    to their original intent — a fake, not a real, Razorpay subscription."""
    import uuid as _uuid
    from app.services import control_hub

    def _fake(plan_name, start_at, notify_email=None, notify_phone=None):
        return {
            "subscription_id": f"sub_mock_{_uuid.uuid4().hex[:8]}",
            "key_id": "rzp_test_mock",
            "short_url": "https://rzp.mock/checkout/sub_mock",
            "status": "created",
        }

    monkeypatch.setattr(control_hub, "create_subscription", _fake)


def test_subscribe_creates_trial(client, auth_headers, db, monkeypatch):
    """POST /billing/subscribe creates a Razorpay subscription in 'created' state with a trial."""
    from app.models.billing import UserSubscription

    _mock_hub_create_subscription(monkeypatch)
    pro = _pro_plan(db)
    assert pro is not None, "Pro plan not seeded"

    resp = client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": str(pro.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["subscription_id"].startswith("sub_mock")  # mock mode (no keys)
    assert data["plan"] == "Pro"
    assert data["amount"] == 199.0
    assert data["currency"] == "INR"
    assert data["trial_days"] == 30
    assert data["trial_end"] is not None

    me = client.get("/api/v1/users/me", headers=auth_headers).json()["data"]
    db.expire_all()
    sub = db.query(UserSubscription).filter(
        UserSubscription.user_id == me["id"]
    ).first()
    assert sub is not None
    assert sub.gateway == "razorpay"
    assert sub.status == "created"
    assert sub.trial_end is not None
    assert sub.razorpay_subscription_id == data["subscription_id"]


def test_subscribe_requires_auth(client, db):
    pro = _pro_plan(db)
    if not pro:
        return
    resp = client.post("/api/v1/billing/subscribe", json={"plan_id": str(pro.id)})
    assert resp.status_code == 401


def test_subscribe_nonexistent_plan(client, auth_headers):
    resp = client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def _rzp_webhook(client, event, sub_id, payment=None, sub_extra=None):
    entity = {"id": sub_id}
    if sub_extra:
        entity.update(sub_extra)
    payload = {"event": event, "payload": {"subscription": {"entity": entity}}}
    if payment is not None:
        payload["payload"]["payment"] = {"entity": payment}
    return client.post(
        "/api/v1/billing/razorpay/webhook",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )


def test_razorpay_webhook_authenticated_then_charged(client, auth_headers, db, monkeypatch):
    """authenticated -> trialing; charged -> active + payment history recorded."""
    from app.models.billing import UserSubscription
    from app.models.payment_history import PaymentHistory

    _mock_hub_create_subscription(monkeypatch)
    pro = _pro_plan(db)
    assert pro is not None

    sub_id = client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": str(pro.id)},
        headers=auth_headers,
    ).json()["data"]["subscription_id"]

    # authenticated → trialing
    r1 = _rzp_webhook(client, "subscription.authenticated", sub_id)
    assert r1.status_code == 200
    db.expire_all()
    sub = db.query(UserSubscription).filter(
        UserSubscription.razorpay_subscription_id == sub_id
    ).first()
    assert sub.status == "trialing"

    # charged → active + payment recorded
    r2 = _rzp_webhook(
        client, "subscription.charged", sub_id,
        payment={"id": "pay_rzp_test_001", "amount": 19900, "currency": "INR"},
        sub_extra={"current_start": 1700000000, "current_end": 1702678400},
    )
    assert r2.status_code == 200
    db.expire_all()
    sub = db.query(UserSubscription).filter(
        UserSubscription.razorpay_subscription_id == sub_id
    ).first()
    assert sub.status == "active"

    pay = db.query(PaymentHistory).filter(
        PaymentHistory.razorpay_payment_id == "pay_rzp_test_001"
    ).first()
    assert pay is not None
    assert float(pay.amount) == 199.0
    assert pay.status == "paid"
    assert pay.gateway == "razorpay"


def test_razorpay_webhook_charged_idempotent(client, auth_headers, db, monkeypatch):
    """Duplicate charged webhook (same payment id) does not double-record."""
    from app.models.payment_history import PaymentHistory

    _mock_hub_create_subscription(monkeypatch)
    pro = _pro_plan(db)
    assert pro is not None
    sub_id = client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": str(pro.id)},
        headers=auth_headers,
    ).json()["data"]["subscription_id"]

    payment = {"id": "pay_rzp_dup_001", "amount": 19900, "currency": "INR"}
    _rzp_webhook(client, "subscription.charged", sub_id, payment=payment)
    _rzp_webhook(client, "subscription.charged", sub_id, payment=payment)

    db.expire_all()
    count = db.query(PaymentHistory).filter(
        PaymentHistory.razorpay_payment_id == "pay_rzp_dup_001"
    ).count()
    assert count == 1


def test_razorpay_webhook_halted_downgrades(client, auth_headers, db, monkeypatch):
    """halted event moves subscription to halted + downgrades to Free plan."""
    from app.models.billing import UserSubscription, BillingPlan

    _mock_hub_create_subscription(monkeypatch)
    pro = _pro_plan(db)
    assert pro is not None
    sub_id = client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": str(pro.id)},
        headers=auth_headers,
    ).json()["data"]["subscription_id"]

    _rzp_webhook(client, "subscription.halted", sub_id)
    db.expire_all()
    sub = db.query(UserSubscription).filter(
        UserSubscription.razorpay_subscription_id == sub_id
    ).first()
    assert sub.status == "halted"
    free = db.query(BillingPlan).filter(BillingPlan.name == "Free").first()
    assert sub.plan_id == free.id


def test_subscribe_blocks_when_active(client, auth_headers, db, monkeypatch):
    """A second subscribe while trialing/active is rejected (no mandate stacking)."""
    _mock_hub_create_subscription(monkeypatch)
    pro = _pro_plan(db)
    assert pro is not None
    sub_id = client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": str(pro.id)},
        headers=auth_headers,
    ).json()["data"]["subscription_id"]
    _rzp_webhook(client, "subscription.authenticated", sub_id)

    resp = client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": str(pro.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_subscribe_integrity_error_maps_to_existing_active_message(
    client, auth_headers, db, monkeypatch
):
    """Deterministic test of the actual new code path: if a DB-level unique-
    constraint violation reaches create_razorpay_subscription's commit (the
    real-world trigger being two concurrent requests that both pass the
    application-level 'existing' check before either commits — verified
    separately against a real Postgres DB, since genuinely racing two
    threads isn't reproducible through this test client's shared-session
    fixture), it must surface as the same user-facing message as the
    application-level check, not a raw 500/502."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    _mock_hub_create_subscription(monkeypatch)
    pro = _pro_plan(db)
    assert pro is not None

    original_commit = Session.commit
    call_count = {"n": 0}

    def _commit_raise_once(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise IntegrityError(
                "INSERT INTO user_subscriptions ...", {},
                Exception("duplicate key value violates unique constraint "
                          '"uq_user_subscriptions_user_id"'),
            )
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(Session, "commit", _commit_raise_once)

    resp = client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": str(pro.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "already have an active subscription" in resp.json()["message"]


def test_plans_sync_from_hub_single_plan(client, db, monkeypatch):
    """When the Control Hub offers a single ₹199 plan, /billing/plans returns only it."""
    from app.services import control_hub

    monkeypatch.setattr(control_hub, "is_configured", lambda: True)
    monkeypatch.setattr(
        control_hub, "fetch_plans",
        lambda: [{
            "name": "Pro", "monthly_price": 199, "yearly_price": 1999,
            "features": ["30-day free trial", "AI Insights"],
            "caps": {"ai_insights": True, "ocr_scans": 100},
        }],
    )
    resp = client.get("/api/v1/billing/plans")
    assert resp.status_code == 200
    plans = resp.json()["data"]
    assert [p["name"] for p in plans] == ["Pro"]
    assert plans[0]["price_monthly"] == 199.0


def test_razorpay_webhook_bad_json(client):
    """Malformed webhook body is swallowed gracefully."""
    resp = client.post(
        "/api/v1/billing/razorpay/webhook",
        content="not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json().get("received") is True
