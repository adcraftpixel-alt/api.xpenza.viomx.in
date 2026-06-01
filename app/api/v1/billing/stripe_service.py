import stripe
from app.config import settings
from typing import Optional

# Initialize Stripe - works with test key or empty key (graceful fallback)
if settings.STRIPE_SECRET_KEY and settings.STRIPE_SECRET_KEY != "sk_test_placeholder":
    stripe.api_key = settings.STRIPE_SECRET_KEY
    STRIPE_ENABLED = True
else:
    STRIPE_ENABLED = False


class StripeService:

    def create_or_get_customer(self, user_id: str, email: str, name: str) -> Optional[str]:
        """Create Stripe customer and return customer ID"""
        if not STRIPE_ENABLED:
            return f"cus_mock_{user_id[:8]}"
        try:
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata={"user_id": user_id}
            )
            return customer.id
        except stripe.StripeError as e:
            raise ValueError(f"Stripe error: {e.user_message}")

    def create_checkout_session(self, customer_id: str, price_id: str,
                                 user_id: str, success_url: str, cancel_url: str) -> dict:
        """Create Stripe Checkout Session"""
        if not STRIPE_ENABLED:
            return {
                "session_id": f"cs_mock_{user_id[:8]}",
                "url": f"{success_url}?session_id=cs_mock",
                "mock": True
            }
        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": 1}],
                mode="subscription",
                success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=cancel_url,
                metadata={"user_id": user_id},
            )
            return {"session_id": session.id, "url": session.url}
        except stripe.StripeError as e:
            raise ValueError(f"Stripe error: {e.user_message}")

    def create_payment_intent(self, customer_id: str, price_id: str, user_id: str) -> dict:
        """Create PaymentIntent for mobile SDK"""
        if not STRIPE_ENABLED:
            return {
                "client_secret": f"pi_mock_{user_id[:8]}_secret_mock",
                "payment_intent_id": f"pi_mock_{user_id[:8]}",
                "mock": True
            }
        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=["latest_invoice.payment_intent"],
                metadata={"user_id": user_id},
            )
            pi = subscription.latest_invoice.payment_intent
            return {
                "client_secret": pi.client_secret,
                "subscription_id": subscription.id,
                "payment_intent_id": pi.id,
            }
        except stripe.StripeError as e:
            raise ValueError(f"Stripe error: {e.user_message}")

    def cancel_subscription(self, stripe_subscription_id: str) -> bool:
        """Cancel at period end"""
        if not STRIPE_ENABLED or stripe_subscription_id.startswith("sub_mock"):
            return True
        try:
            stripe.Subscription.modify(
                stripe_subscription_id,
                cancel_at_period_end=True
            )
            return True
        except stripe.StripeError:
            return False

    def reactivate_subscription(self, stripe_subscription_id: str) -> bool:
        """Undo cancel_at_period_end"""
        if not STRIPE_ENABLED or stripe_subscription_id.startswith("sub_mock"):
            return True
        try:
            stripe.Subscription.modify(
                stripe_subscription_id,
                cancel_at_period_end=False
            )
            return True
        except stripe.StripeError:
            return False

    def upgrade_subscription(self, stripe_subscription_id: str, new_price_id: str) -> bool:
        """Change plan with immediate proration"""
        if not STRIPE_ENABLED or stripe_subscription_id.startswith("sub_mock"):
            return True
        try:
            sub = stripe.Subscription.retrieve(stripe_subscription_id)
            stripe.Subscription.modify(
                stripe_subscription_id,
                items=[{"id": sub["items"]["data"][0]["id"], "price": new_price_id}],
                proration_behavior="create_prorations",
            )
            return True
        except stripe.StripeError:
            return False

    def get_invoices(self, stripe_customer_id: str, limit: int = 20) -> list:
        """Fetch customer invoices from Stripe"""
        if not STRIPE_ENABLED or stripe_customer_id.startswith("cus_mock"):
            return []
        try:
            invoices = stripe.Invoice.list(customer=stripe_customer_id, limit=limit)
            return [
                {
                    "id": inv.id,
                    "amount": inv.amount_paid / 100,
                    "currency": inv.currency.upper(),
                    "status": inv.status,
                    "pdf_url": inv.invoice_pdf,
                    "created": inv.created,
                }
                for inv in invoices.data
            ]
        except stripe.StripeError:
            return []

    def construct_webhook_event(self, payload: bytes, sig_header: str) -> dict:
        """Verify and parse webhook"""
        if not STRIPE_ENABLED:
            raise ValueError("Stripe not configured")
        return stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )


stripe_service = StripeService()
