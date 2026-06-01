from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
import uuid

from app.api.v1.billing.stripe_service import stripe_service
from app.models.billing import BillingPlan, UserSubscription
from app.models.payment_history import PaymentHistory
from app.models.user import User
from app.utils.response import success


class BillingService:

    def get_plans(self, db: Session) -> list:
        plans = db.query(BillingPlan).filter(BillingPlan.is_active == True).all()
        return [
            {
                "id": str(p.id),
                "name": p.name,
                "price_monthly": float(p.price_monthly) if p.price_monthly else 0,
                "price_yearly": float(p.price_yearly) if p.price_yearly else 0,
                "stripe_price_id_monthly": p.stripe_price_id_monthly,
                "stripe_price_id_yearly": p.stripe_price_id_yearly,
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
            "price_monthly": float(sub.price_monthly) if sub.price_monthly else 0,
            "features": sub.features or {},
            "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "cancel_at_period_end": sub.cancel_at_period_end,
            "stripe_subscription_id": sub.stripe_subscription_id,
        }

    def cancel_subscription(self, user_id: str, db: Session) -> dict:
        sub = db.query(UserSubscription).filter(
            UserSubscription.user_id == user_id
        ).first()
        if not sub:
            raise ValueError("No active subscription found")

        if sub.stripe_subscription_id:
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
