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
