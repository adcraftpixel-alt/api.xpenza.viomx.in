"""
Read-only data feed for the VIOMX Control Hub (machine-to-machine).

Exposes users, payment transactions, payment methods and wallet funding so the
Control Hub can display live Rupexi data. All methods are read-only.
"""
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.payment_history import PaymentHistory
from app.models.billing import UserSubscription, BillingPlan
from app.models.expense import Expense
from app.models.wallet import Wallet, WalletTransaction


def _iso(dt):
    return dt.isoformat() if dt else None


class ServiceFeed:
    # ── Summary ─────────────────────────────────────────────────────────────
    def stats(self, db: Session) -> dict:
        total_users = db.query(func.count(User.id)).scalar() or 0
        active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0
        paid_total = (
            db.query(func.coalesce(func.sum(PaymentHistory.amount), 0))
            .filter(PaymentHistory.status == "paid")
            .scalar()
            or 0
        )
        payment_count = db.query(func.count(PaymentHistory.id)).scalar() or 0
        active_subs = (
            db.query(func.count(UserSubscription.id))
            .filter(UserSubscription.status.in_(["active", "trialing"]))
            .scalar()
            or 0
        )
        wallet_funded = (
            db.query(func.coalesce(func.sum(Wallet.allocated), 0)).scalar() or 0
        )
        return {
            "total_users": int(total_users),
            "active_users": int(active_users),
            "total_revenue": float(paid_total),
            "payment_count": int(payment_count),
            "active_subscriptions": int(active_subs),
            "total_wallet_funding": float(wallet_funded),
            "currency": "INR",
        }

    # ── Users ───────────────────────────────────────────────────────────────
    def list_users(
        self, db: Session, page: int = 1, limit: int = 50, search: Optional[str] = None
    ) -> dict:
        q = db.query(User)
        if search:
            like = f"%{search}%"
            q = q.filter((User.email.ilike(like)) | (User.name.ilike(like)))
        total = q.count()
        rows = (
            q.order_by(User.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        # Resolve current plan name per user in one pass.
        user_ids = [u.id for u in rows]
        plan_by_user: dict[str, str] = {}
        if user_ids:
            sub_rows = (
                db.query(UserSubscription.user_id, BillingPlan.name, UserSubscription.status)
                .join(BillingPlan, BillingPlan.id == UserSubscription.plan_id, isouter=True)
                .filter(UserSubscription.user_id.in_(user_ids))
                .all()
            )
            for uid, plan_name, _status in sub_rows:
                plan_by_user[uid] = plan_name or "Free"

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "id": str(u.id),
                    "email": u.email,
                    "name": u.name,
                    "phone": u.phone,
                    "currency": u.currency,
                    "plan": plan_by_user.get(u.id, "Free"),
                    "is_active": u.is_active,
                    "is_verified": u.is_verified,
                    "created_at": _iso(u.created_at),
                }
                for u in rows
            ],
        }

    # ── Payment transactions ─────────────────────────────────────────────────
    def list_payments(self, db: Session, page: int = 1, limit: int = 50) -> dict:
        q = db.query(PaymentHistory, User).join(
            User, User.id == PaymentHistory.user_id, isouter=True
        )
        total = q.count()
        rows = (
            q.order_by(PaymentHistory.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        items = []
        for ph, user in rows:
            gateway = ph.gateway or ("razorpay" if ph.razorpay_payment_id else "stripe")
            payment_id = (
                ph.razorpay_payment_id
                or ph.stripe_payment_id
                or ph.razorpay_invoice_id
                or ph.stripe_invoice_id
                or str(ph.id)
            )
            items.append(
                {
                    "id": str(ph.id),
                    "payment_id": payment_id,
                    "user_id": str(ph.user_id),
                    "user_email": user.email if user else None,
                    "amount": float(ph.amount) if ph.amount is not None else 0.0,
                    "currency": ph.currency or "INR",
                    "status": ph.status,
                    "gateway": gateway,
                    "paid_at": _iso(ph.paid_at),
                    "created_at": _iso(ph.created_at),
                }
            )
        return {"total": total, "page": page, "limit": limit, "items": items}

    # ── Payment methods ───────────────────────────────────────────────────────
    def payment_methods(self, db: Session) -> dict:
        """Mandates (auto-pay) + the payment methods users actually use on expenses."""
        mandates = []
        sub_rows = (
            db.query(UserSubscription, User, BillingPlan)
            .join(User, User.id == UserSubscription.user_id, isouter=True)
            .join(BillingPlan, BillingPlan.id == UserSubscription.plan_id, isouter=True)
            .all()
        )
        for sub, user, plan in sub_rows:
            reference = sub.razorpay_subscription_id or sub.stripe_subscription_id
            mandates.append(
                {
                    "user_id": str(sub.user_id),
                    "user_email": user.email if user else None,
                    "gateway": sub.gateway,
                    "plan": plan.name if plan else None,
                    "status": sub.status,
                    "reference": reference,
                    "trial_end": _iso(sub.trial_end),
                }
            )

        method_rows = (
            db.query(
                Expense.payment_method,
                func.count(Expense.id).label("count"),
            )
            .filter(Expense.payment_method.isnot(None))
            .group_by(Expense.payment_method)
            .all()
        )
        methods = [
            {"method": m or "unknown", "usage_count": int(c)} for m, c in method_rows
        ]
        return {"mandates": mandates, "expense_methods": methods}

    # ── Block / unblock (Control Hub → Rupexi) ──────────────────────────────────
    def set_user_active(self, db: Session, user_id: str, active: bool) -> dict:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")
        user.is_active = active
        db.commit()
        return {"user_id": str(user.id), "is_active": user.is_active}

    # ── Wallet funding ─────────────────────────────────────────────────────────
    def funding(self, db: Session, page: int = 1, limit: int = 50) -> dict:
        q = db.query(Wallet, User).join(User, User.id == Wallet.user_id, isouter=True)
        total = q.count()
        rows = (
            q.order_by(Wallet.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        items = []
        for wallet, user in rows:
            credited = (
                db.query(func.coalesce(func.sum(WalletTransaction.amount), 0))
                .filter(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.type == "credit",
                )
                .scalar()
                or 0
            )
            debited = (
                db.query(func.coalesce(func.sum(WalletTransaction.amount), 0))
                .filter(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.type == "debit",
                )
                .scalar()
                or 0
            )
            tx_count = (
                db.query(func.count(WalletTransaction.id))
                .filter(WalletTransaction.wallet_id == wallet.id)
                .scalar()
                or 0
            )
            items.append(
                {
                    "id": str(wallet.id),
                    "user_id": str(wallet.user_id),
                    "user_email": user.email if user else None,
                    "name": wallet.name,
                    "icon": wallet.icon,
                    "color": wallet.color,
                    "allocated": float(wallet.allocated) if wallet.allocated is not None else 0.0,
                    "credited": float(credited),
                    "debited": float(debited),
                    "transaction_count": int(tx_count),
                    "is_active": wallet.is_active,
                    "created_at": _iso(wallet.created_at),
                }
            )
        return {"total": total, "page": page, "limit": limit, "items": items}


service_feed = ServiceFeed()
