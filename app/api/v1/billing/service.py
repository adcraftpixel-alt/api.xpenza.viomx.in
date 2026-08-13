from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
from typing import Optional
import uuid

from app.config import settings
from app.api.v1.billing.stripe_service import stripe_service
from app.models.billing import BillingPlan, UserSubscription
from app.models.payment_history import PaymentHistory
from app.models.user import User
from app.utils.response import success


class BillingService:

    def _sync_plans_from_hub(self, db: Session) -> None:
        """Pull plans/pricing/caps from the Control Hub (source of truth)."""
        from app.services import control_hub

        hub_plans = control_hub.fetch_plans()
        if not hub_plans:
            return
        hub_names = set()
        for hp in hub_plans:
            name = hp.get("name")
            if not name:
                continue
            hub_names.add(name)
            plan = db.query(BillingPlan).filter(BillingPlan.name == name).first()
            if not plan:
                plan = BillingPlan(id=str(uuid.uuid4()), name=name)
                db.add(plan)
            plan.is_active = True
            plan.price_monthly = hp.get("monthly_price") or 0
            plan.price_yearly = hp.get("yearly_price") or 0
            plan.features = hp.get("features") or []
            plan.caps = hp.get("caps") or {}

        # The Hub is the source of truth: hide any local plan it no longer offers
        # (e.g. Free/Business) so /billing/plans returns exactly the Hub's plans.
        # Rows are kept (deactivated) so downgrade/fallback lookups by name still work.
        for p in db.query(BillingPlan).filter(BillingPlan.is_active == True).all():
            if p.name not in hub_names:
                p.is_active = False
        db.commit()

    def get_plans(self, db: Session) -> list:
        # Keep local plans in sync with the Control Hub before returning them.
        try:
            self._sync_plans_from_hub(db)
        except Exception:
            db.rollback()  # never let a Hub hiccup break the pricing screen
        plans = db.query(BillingPlan).filter(BillingPlan.is_active == True).all()
        return [
            {
                "id": str(p.id),
                "name": p.name,
                "price_monthly": float(p.price_monthly) if p.price_monthly else 0,
                "price_yearly": float(p.price_yearly) if p.price_yearly else 0,
                "stripe_price_id_monthly": p.stripe_price_id_monthly,
                "stripe_price_id_yearly": p.stripe_price_id_yearly,
                "razorpay_plan_id": p.razorpay_plan_id,
                "features": p.features or {},
                "is_active": p.is_active,
            }
            for p in plans
        ]

    def create_checkout(self, user: User, plan_id: str, interval: str, db: Session) -> dict:
        """Create Stripe checkout — returns client_secret for mobile SDK"""
        plan = db.query(BillingPlan).filter(BillingPlan.id == plan_id).first()
        if not plan:
            raise ValueError("Plan not found")

        # Get or create Stripe customer
        if not user.stripe_customer_id:
            customer_id = stripe_service.create_or_get_customer(
                str(user.id), user.email, user.name
            )
            user.stripe_customer_id = customer_id
            db.commit()

        price_id = plan.stripe_price_id_monthly if interval == "monthly" else plan.stripe_price_id_yearly

        if not price_id:
            # Free plan or enterprise — no Stripe needed
            self._activate_plan(user, plan, db)
            return {"client_secret": None, "plan": plan.name, "activated": True}

        result = stripe_service.create_payment_intent(
            user.stripe_customer_id, price_id, str(user.id)
        )
        return result

    # ── Razorpay: trial + ₹199/mo auto-pay ──────────────────────────────────
    def create_razorpay_subscription(self, user: User, plan_id: str, db: Session) -> dict:
        """
        Start the trial → auto-pay flow.

        Creates a Razorpay Subscription via the Control Hub — Rupexi holds no
        Razorpay credentials itself; the Hub creates the Subscription with its
        centrally-stored secret and returns only the publishable key_id needed
        by the mobile Razorpay Checkout. The first debit is `TRIAL_DAYS` in the
        future (the free trial); the ₹1 validation charge during mandate setup
        is done + auto-refunded by Razorpay. We persist a local subscription row
        in 'created' state; webhooks (relayed from the Hub) move it to
        trialing/active.
        """
        from app.services import control_hub

        plan = db.query(BillingPlan).filter(BillingPlan.id == plan_id).first()
        if not plan:
            raise ValueError("Plan not found")

        try:
            # Guard against stacking / trial abuse: one active mandate per user.
            existing = db.query(UserSubscription).filter(
                UserSubscription.user_id == user.id
            ).first()
            if existing and existing.status in ("trialing", "active", "past_due"):
                raise ValueError("You already have an active subscription")

            trial_days = settings.TRIAL_DAYS
            trial_end = datetime.utcnow() + timedelta(days=trial_days)
            start_at = int(trial_end.timestamp())

            result = control_hub.create_subscription(
                plan_name=plan.name,
                start_at=start_at,
                notify_email=user.email,
                notify_phone=user.phone,
            )

            if existing:
                existing.plan_id = plan.id
                existing.gateway = "razorpay"
                existing.razorpay_subscription_id = result["subscription_id"]
                existing.status = "created"
                existing.trial_end = trial_end
                existing.cancel_at_period_end = False
            else:
                db.add(UserSubscription(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    plan_id=plan.id,
                    gateway="razorpay",
                    razorpay_subscription_id=result["subscription_id"],
                    status="created",
                    trial_end=trial_end,
                ))
            db.commit()
        except ValueError:
            db.rollback()
            raise
        except (control_hub.HubNotConfigured, control_hub.HubRequestError) as e:
            db.rollback()
            raise ValueError(str(e))
        except Exception as e:
            # Any unexpected DB/runtime failure — roll back so the transaction
            # isn't left broken for a retry, and surface a real message instead
            # of letting an opaque 500 reach the client.
            db.rollback()
            raise ValueError(f"Could not start subscription: {e}")

        return {
            "subscription_id": result["subscription_id"],
            "razorpay_key_id": result.get("key_id", ""),
            "short_url": result.get("short_url"),
            "plan": plan.name,
            "amount": float(plan.price_monthly) if plan.price_monthly else 0.0,
            "currency": "INR",
            "trial_end": trial_end.isoformat(),
            "trial_days": trial_days,
        }

    def _report_purchase_to_hub(
        self, db: Session, sub: UserSubscription, amount: float,
        payment_id: str, status: str, is_trial: bool,
    ):
        """Report a buyer + purchase to the Control Hub (best-effort)."""
        from app.services import control_hub

        if not control_hub.is_configured():
            return
        try:
            user = db.query(User).filter(User.id == sub.user_id).first()
            plan = db.query(BillingPlan).filter(BillingPlan.id == sub.plan_id).first()
            if not user:
                return
            control_hub.report_purchase({
                "external_user_id": str(user.id),
                "email": user.email,
                "name": user.name,
                "plan_name": plan.name if plan else "Pro",
                "amount": float(amount or 0),
                "currency": "INR",
                "payment_id": payment_id,
                "gateway": sub.gateway or "razorpay",
                "status": status,
                "billing_cycle": "monthly",
                "is_trial": is_trial,
                "period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            })
        except Exception:
            pass  # never let reporting break billing

    def _notify_trial_started(self, sub: UserSubscription, db: Session):
        """In-app + push notification telling the user their free month has
        started and when the first auto-debit happens (best-effort)."""
        try:
            plan = db.query(BillingPlan).filter(BillingPlan.id == sub.plan_id).first()
            price = float(plan.price_monthly) if plan and plan.price_monthly else 0
            trial_end_label = (
                sub.trial_end.strftime("%d %b %Y") if sub.trial_end else "your trial end date"
            )
            title = "Your free trial has started! 🎉"
            body = (
                f"Enjoy 30 days free. ₹{price:,.0f}/month starts automatically on "
                f"{trial_end_label}. Cancel anytime before then."
            )

            db.execute(text("""
                INSERT INTO notifications (id, user_id, title, body, type, is_read, data, created_at)
                VALUES (:id, :uid, :title, :body, 'trial_started', false, CAST(:data AS JSONB), NOW())
            """), {
                "id": str(uuid.uuid4()),
                "uid": str(sub.user_id),
                "title": title,
                "body": body,
                "data": (
                    f'{{"amount": {price}, '
                    f'"trial_end": "{sub.trial_end.isoformat() if sub.trial_end else ""}"}}'
                ),
            })
            db.commit()

            token_row = db.execute(text(
                "SELECT device_token FROM user_device_tokens WHERE user_id = :uid LIMIT 1"
            ), {"uid": str(sub.user_id)}).first()
            if token_row and token_row[0]:
                from app.utils.fcm import send_push_notification
                send_push_notification(
                    token_row[0], title, body,
                    {"type": "trial_started", "amount": str(price)},
                    "trial_started",
                )
        except Exception:
            # Never let a notification failure break the billing webhook —
            # but roll back so a failed INSERT doesn't poison the caller's
            # transaction for whatever runs next in this request.
            db.rollback()

    def handle_razorpay_webhook(self, event: str, body: dict, db: Session):
        """React to Razorpay subscription lifecycle events (state machine)."""
        payload = body.get("payload", {})
        sub_entity = (payload.get("subscription", {}) or {}).get("entity", {}) or {}
        payment_entity = (payload.get("payment", {}) or {}).get("entity", {}) or {}

        if event == "subscription.authenticated":
            # Mandate registered; free trial running.
            self._rzp_set_status(sub_entity, "trialing", db)
            sub = self._rzp_find(sub_entity, db)
            if sub:
                self._report_purchase_to_hub(
                    db, sub, amount=0,
                    payment_id=f"trial_{sub.razorpay_subscription_id}",
                    status="trial", is_trial=True,
                )
                self._notify_trial_started(sub, db)
        elif event == "subscription.activated":
            # First ₹199 debit succeeded at trial end.
            self._rzp_set_status(sub_entity, "active", db)
        elif event == "subscription.charged":
            self._rzp_handle_charged(sub_entity, payment_entity, db)
        elif event == "subscription.pending":
            # A recurring debit failed; Razorpay retrying.
            self._rzp_set_status(sub_entity, "past_due", db)
        elif event == "subscription.halted":
            # Retries exhausted.
            self._rzp_downgrade(sub_entity, "halted", db)
        elif event in ("subscription.cancelled", "subscription.completed"):
            self._rzp_downgrade(sub_entity, "canceled", db)

    def _rzp_find(self, sub_entity: dict, db: Session) -> Optional[UserSubscription]:
        sub_id = sub_entity.get("id")
        if not sub_id:
            return None
        return db.query(UserSubscription).filter(
            UserSubscription.razorpay_subscription_id == sub_id
        ).first()

    def _rzp_apply_period(self, sub: UserSubscription, sub_entity: dict):
        cs, ce = sub_entity.get("current_start"), sub_entity.get("current_end")
        if cs:
            sub.current_period_start = datetime.fromtimestamp(cs)
        if ce:
            sub.current_period_end = datetime.fromtimestamp(ce)

    def _rzp_set_status(self, sub_entity: dict, status: str, db: Session):
        sub = self._rzp_find(sub_entity, db)
        if not sub:
            return
        sub.status = status
        self._rzp_apply_period(sub, sub_entity)
        db.commit()

    def _rzp_handle_charged(self, sub_entity: dict, payment_entity: dict, db: Session):
        sub = self._rzp_find(sub_entity, db)
        if not sub:
            return
        sub.status = "active"
        self._rzp_apply_period(sub, sub_entity)

        pay_id = payment_entity.get("id")
        # Idempotency: Razorpay retries webhooks — skip if already recorded.
        if pay_id:
            dup = db.query(PaymentHistory).filter(
                PaymentHistory.razorpay_payment_id == pay_id
            ).first()
            if dup:
                db.commit()
                return

        amt = (payment_entity.get("amount", 0) / 100) if payment_entity.get("amount") else None
        db.add(PaymentHistory(
            id=str(uuid.uuid4()),
            user_id=sub.user_id,
            subscription_id=sub.id,
            razorpay_payment_id=pay_id,
            razorpay_invoice_id=sub_entity.get("id"),
            gateway="razorpay",
            amount=amt,
            currency=(payment_entity.get("currency") or "INR").upper(),
            status="paid",
            paid_at=datetime.utcnow(),
        ))
        db.commit()

        # Report the successful charge to the Control Hub (buyer + transaction).
        self._report_purchase_to_hub(
            db, sub, amount=amt or 0,
            payment_id=pay_id or f"charge_{sub.razorpay_subscription_id}",
            status="success", is_trial=False,
        )

    def _rzp_downgrade(self, sub_entity: dict, status: str, db: Session):
        sub = self._rzp_find(sub_entity, db)
        if not sub:
            return
        sub.status = status
        free_plan = db.execute(text(
            "SELECT id FROM billing_plans WHERE name = 'Free' LIMIT 1"
        )).fetchone()
        if free_plan:
            sub.plan_id = free_plan.id
        db.commit()

    def _activate_plan(self, user: User, plan: BillingPlan, db: Session):
        """Directly activate plan (for free plan or manual activation)"""
        existing = db.query(UserSubscription).filter(
            UserSubscription.user_id == user.id
        ).first()

        now = datetime.utcnow()
        if existing:
            existing.plan_id = plan.id
            existing.status = "active"
            existing.current_period_start = now
            existing.cancel_at_period_end = False
        else:
            sub = UserSubscription(
                id=str(uuid.uuid4()),
                user_id=user.id,
                plan_id=plan.id,
                status="active",
                current_period_start=now,
            )
            db.add(sub)
        db.commit()

    def get_current_subscription(self, user_id: str, db: Session) -> Optional[dict]:
        sub = db.execute(text("""
            SELECT us.id, us.status, us.current_period_start, us.current_period_end,
                   us.cancel_at_period_end, us.stripe_subscription_id,
                   us.razorpay_subscription_id, us.gateway, us.trial_end,
                   bp.name as plan_name, bp.price_monthly, bp.features
            FROM user_subscriptions us
            JOIN billing_plans bp ON bp.id = us.plan_id
            WHERE us.user_id = :uid
            LIMIT 1
        """), {"uid": user_id}).fetchone()

        if not sub:
            # Return free plan details
            free_plan = db.execute(text(
                "SELECT id, name, features FROM billing_plans WHERE name = 'Free' LIMIT 1"
            )).fetchone()
            return {
                "plan": "Free",
                "status": "active",
                "features": free_plan.features if free_plan else {},
                "cancel_at_period_end": False,
            }

        return {
            "id": str(sub.id),
            "plan": sub.plan_name,
            "status": sub.status,
            "gateway": sub.gateway,
            "is_trialing": sub.status == "trialing",
            "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
            "price_monthly": float(sub.price_monthly) if sub.price_monthly else 0,
            "features": sub.features or {},
            "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "cancel_at_period_end": sub.cancel_at_period_end,
            "stripe_subscription_id": sub.stripe_subscription_id,
            "razorpay_subscription_id": sub.razorpay_subscription_id,
        }

    def cancel_subscription(self, user_id: str, db: Session) -> dict:
        from app.services import control_hub

        sub = db.query(UserSubscription).filter(
            UserSubscription.user_id == user_id
        ).first()
        if not sub:
            raise ValueError("No active subscription found")

        if sub.gateway == "razorpay" and sub.razorpay_subscription_id:
            # Cancels the mandate via the Control Hub; works during the trial
            # (before any auto-debit) since Rupexi holds no Razorpay credentials.
            try:
                control_hub.cancel_subscription(sub.razorpay_subscription_id, at_cycle_end=True)
            except (control_hub.HubNotConfigured, control_hub.HubRequestError) as e:
                raise ValueError(str(e))
        elif sub.stripe_subscription_id:
            stripe_service.cancel_subscription(sub.stripe_subscription_id)

        sub.cancel_at_period_end = True
        db.commit()
        return {"message": "Subscription will cancel at period end", "cancel_at_period_end": True}

    def handle_webhook(self, event_type: str, event_data: dict, db: Session):
        """Process Stripe webhook events"""
        obj = event_data.get("object", {})

        if event_type == "customer.subscription.created":
            self._handle_subscription_created(obj, db)
        elif event_type == "customer.subscription.updated":
            self._handle_subscription_updated(obj, db)
        elif event_type == "customer.subscription.deleted":
            self._handle_subscription_deleted(obj, db)
        elif event_type == "invoice.payment_succeeded":
            self._handle_payment_succeeded(obj, db)
        elif event_type == "invoice.payment_failed":
            self._handle_payment_failed(obj, db)

    def _handle_subscription_created(self, sub_obj: dict, db: Session):
        user_id = sub_obj.get("metadata", {}).get("user_id")
        if not user_id:
            return

        # Find plan by stripe price ID
        price_id = sub_obj.get("items", {}).get("data", [{}])[0].get("price", {}).get("id")
        plan = db.execute(text("""
            SELECT id FROM billing_plans
            WHERE stripe_price_id_monthly = :pid OR stripe_price_id_yearly = :pid
        """), {"pid": price_id}).fetchone()

        if not plan:
            return

        now = datetime.utcnow()
        existing = db.query(UserSubscription).filter(
            UserSubscription.user_id == user_id
        ).first()

        if existing:
            existing.plan_id = plan.id
            existing.stripe_subscription_id = sub_obj["id"]
            existing.status = sub_obj["status"]
            existing.current_period_start = datetime.fromtimestamp(sub_obj.get("current_period_start", now.timestamp()))
            existing.current_period_end = datetime.fromtimestamp(sub_obj.get("current_period_end", now.timestamp()))
        else:
            db.add(UserSubscription(
                id=str(uuid.uuid4()),
                user_id=user_id,
                plan_id=plan.id,
                stripe_subscription_id=sub_obj["id"],
                status=sub_obj["status"],
                current_period_start=datetime.fromtimestamp(sub_obj.get("current_period_start", now.timestamp())),
                current_period_end=datetime.fromtimestamp(sub_obj.get("current_period_end", now.timestamp())),
            ))
        db.commit()

    def _handle_subscription_updated(self, sub_obj: dict, db: Session):
        sub = db.query(UserSubscription).filter(
            UserSubscription.stripe_subscription_id == sub_obj["id"]
        ).first()
        if sub:
            sub.status = sub_obj.get("status", sub.status)
            sub.cancel_at_period_end = sub_obj.get("cancel_at_period_end", False)
            db.commit()

    def _handle_subscription_deleted(self, sub_obj: dict, db: Session):
        sub = db.query(UserSubscription).filter(
            UserSubscription.stripe_subscription_id == sub_obj["id"]
        ).first()
        if sub:
            # Downgrade to free
            free_plan = db.execute(text(
                "SELECT id FROM billing_plans WHERE name = 'Free' LIMIT 1"
            )).fetchone()
            if free_plan:
                sub.plan_id = free_plan.id
            sub.status = "canceled"
            db.commit()

    def _handle_payment_succeeded(self, invoice_obj: dict, db: Session):
        customer_id = invoice_obj.get("customer")
        user = db.execute(text(
            "SELECT id FROM users WHERE stripe_customer_id = :cid"
        ), {"cid": customer_id}).fetchone()

        if user:
            db.add(PaymentHistory(
                id=str(uuid.uuid4()),
                user_id=user.id,
                stripe_invoice_id=invoice_obj.get("id"),
                amount=(invoice_obj.get("amount_paid", 0) / 100),
                currency=invoice_obj.get("currency", "inr").upper(),
                status="paid",
                invoice_pdf_url=invoice_obj.get("invoice_pdf"),
                paid_at=datetime.fromtimestamp(invoice_obj.get("status_transitions", {}).get("paid_at", 0)) if invoice_obj.get("status_transitions", {}).get("paid_at") else datetime.utcnow(),
            ))
            db.commit()

    def _handle_payment_failed(self, invoice_obj: dict, db: Session):
        customer_id = invoice_obj.get("customer")
        user = db.execute(text(
            "SELECT id FROM users WHERE stripe_customer_id = :cid"
        ), {"cid": customer_id}).fetchone()
        if user:
            db.add(PaymentHistory(
                id=str(uuid.uuid4()),
                user_id=user.id,
                stripe_invoice_id=invoice_obj.get("id"),
                amount=(invoice_obj.get("amount_due", 0) / 100),
                status="failed",
            ))
            db.commit()

    def get_invoices(self, user: User, db: Session) -> list:
        # DB invoices
        db_invoices = db.execute(text("""
            SELECT stripe_invoice_id, amount, currency, status, invoice_pdf_url, paid_at, created_at
            FROM payment_history WHERE user_id = :uid ORDER BY created_at DESC LIMIT 20
        """), {"uid": str(user.id)}).fetchall()

        result = [
            {
                "id": r.stripe_invoice_id or str(uuid.uuid4()),
                "amount": float(r.amount) if r.amount else 0,
                "currency": r.currency or "INR",
                "status": r.status,
                "pdf_url": r.invoice_pdf_url,
                "date": r.paid_at.isoformat() if r.paid_at else r.created_at.isoformat(),
            }
            for r in db_invoices
        ]

        # Also fetch from Stripe if connected
        if user.stripe_customer_id and not user.stripe_customer_id.startswith("cus_mock"):
            stripe_invoices = stripe_service.get_invoices(user.stripe_customer_id)
            result.extend(stripe_invoices)

        return result


billing_service = BillingService()
