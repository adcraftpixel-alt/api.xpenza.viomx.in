"""
Razorpay Subscriptions service — INR recurring auto-pay (UPI AutoPay + card e-mandate).

Flow implemented by the callers of this service:
  1. A Plan (₹199/month) is created once and its id stored on billing_plans.razorpay_plan_id.
  2. On subscribe, a Subscription is created with `start_at` = now + TRIAL_DAYS (the free
     trial) and `customer_notify=1` so Razorpay sends the RBI-mandated 24h pre-debit notice.
  3. The mobile Razorpay Checkout authorises the mandate. Razorpay debits a nominal amount
     (₹1–₹2) to validate the card/UPI mandate and AUTO-REFUNDS it — this is the "₹1 charge".
     We pass NO upfront amount, so nothing is actually kept during the trial.
  4. Razorpay initiates every ₹199 debit itself from `start_at` onward; we only react to
     webhooks. No Celery charging job is required.

Mirrors stripe_service.py: graceful mock fallback when keys are absent (dev/test).
"""
from typing import Optional

from app.config import settings

try:
    import razorpay
    _HAS_SDK = True
except ImportError:  # pragma: no cover - SDK optional in some environments
    razorpay = None
    _HAS_SDK = False

RAZORPAY_ENABLED = bool(
    _HAS_SDK and settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET
)

# One paisa = 1/100 INR. ₹199 -> 19900 paise.
PLAN_AMOUNT_PAISE = 19900


class RazorpayService:
    def __init__(self):
        self._client = None
        if RAZORPAY_ENABLED:
            self._client = razorpay.Client(
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            )

    # ── Plan ────────────────────────────────────────────────────────────────
    def create_plan(
        self, name: str, amount_paise: int = PLAN_AMOUNT_PAISE, period: str = "monthly"
    ) -> str:
        """Create a recurring Plan and return its razorpay plan id."""
        if not RAZORPAY_ENABLED:
            return f"plan_mock_{name.lower().replace(' ', '_')}"
        try:
            plan = self._client.plan.create(
                {
                    "period": period,      # monthly | yearly | weekly | daily
                    "interval": 1,
                    "item": {
                        "name": name,
                        "amount": amount_paise,
                        "currency": "INR",
                    },
                }
            )
            return plan["id"]
        except Exception as e:  # razorpay.errors.*
            raise ValueError(f"Razorpay plan error: {e}")

    # ── Subscription ──────────────────────────────────────────────────────────
    def create_subscription(
        self,
        plan_id: str,
        start_at: int,
        user_id: str,
        total_count: int = 12,
        notify_email: Optional[str] = None,
        notify_phone: Optional[str] = None,
    ) -> dict:
        """
        Create a Subscription with a future `start_at` (the free trial).

        Returns dict with subscription id, short_url (hosted fallback) and status.
        """
        if not RAZORPAY_ENABLED:
            short = user_id[:8]
            return {
                "subscription_id": f"sub_mock_{short}",
                "short_url": f"https://rzp.mock/checkout/sub_mock_{short}",
                "status": "created",
                "mock": True,
            }
        try:
            payload = {
                "plan_id": plan_id,
                "total_count": total_count,
                "customer_notify": 1,          # Razorpay sends pre-debit notifications
                "start_at": start_at,          # unix ts in the future = trial period
                "notes": {"user_id": user_id},
            }
            notify_info = {}
            if notify_email:
                notify_info["email"] = notify_email
            if notify_phone:
                notify_info["phone"] = notify_phone
            if notify_info:
                payload["notify_info"] = notify_info

            sub = self._client.subscription.create(payload)
            return {
                "subscription_id": sub["id"],
                "short_url": sub.get("short_url"),
                "status": sub.get("status", "created"),
            }
        except Exception as e:
            raise ValueError(f"Razorpay subscription error: {e}")

    def cancel_subscription(self, subscription_id: str, at_cycle_end: bool = True) -> bool:
        """Cancel a subscription. Works during the trial (before any ₹199 charge)."""
        if not RAZORPAY_ENABLED or subscription_id.startswith("sub_mock"):
            return True
        try:
            # cancel_at_cycle_end: 1 keeps access until the paid period ends, 0 = now.
            self._client.subscription.cancel(
                subscription_id, {"cancel_at_cycle_end": 1 if at_cycle_end else 0}
            )
            return True
        except Exception:
            return False

    def fetch_subscription(self, subscription_id: str) -> Optional[dict]:
        if not RAZORPAY_ENABLED or subscription_id.startswith("sub_mock"):
            return None
        try:
            return self._client.subscription.fetch(subscription_id)
        except Exception:
            return None

    # ── Webhook ────────────────────────────────────────────────────────────────
    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify the X-Razorpay-Signature header against the webhook secret."""
        if not RAZORPAY_ENABLED or not settings.RAZORPAY_WEBHOOK_SECRET:
            # In dev/test without keys, skip verification (router gates on this too).
            return True
        try:
            self._client.utility.verify_webhook_signature(
                payload.decode("utf-8"),
                signature,
                settings.RAZORPAY_WEBHOOK_SECRET,
            )
            return True
        except Exception:
            return False


razorpay_service = RazorpayService()
