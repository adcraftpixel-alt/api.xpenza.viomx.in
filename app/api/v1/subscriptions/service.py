from datetime import date, datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.api.v1.subscriptions.schemas import CreateSubscriptionRequest, UpdateSubscriptionRequest
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.subscription import TrackedSubscription


def _days_until(renewal_date: Optional[date]) -> Optional[int]:
    if renewal_date is None:
        return None
    delta = renewal_date - date.today()
    return delta.days


def _sub_to_dict(s: TrackedSubscription) -> dict:
    return {
        "id": str(s.id),
        "user_id": str(s.user_id),
        "name": s.name,
        "amount": float(s.amount),
        "billing_cycle": s.billing_cycle,
        "next_renewal": str(s.next_renewal) if s.next_renewal else None,
        "category": s.category,
        "is_active": s.is_active,
        "detected_by_ai": s.detected_by_ai,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "days_until_renewal": _days_until(s.next_renewal),
    }


class SubscriptionService:
    def list(self, db: Session, user_id: str) -> List[dict]:
        subs = (
            db.query(TrackedSubscription)
            .filter(TrackedSubscription.user_id == user_id)
            .order_by(TrackedSubscription.created_at.desc())
            .all()
        )
        return [_sub_to_dict(s) for s in subs]

    def get_by_id(self, db: Session, sub_id: str, user_id: str) -> dict:
        s = db.query(TrackedSubscription).filter(TrackedSubscription.id == sub_id).first()
        if not s:
            raise NotFoundError("Subscription not found")
        if str(s.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        return _sub_to_dict(s)

    def create(self, db: Session, user_id: str, data: CreateSubscriptionRequest) -> dict:
        sub = TrackedSubscription(
            user_id=user_id,
            name=data.name,
            amount=data.amount,
            billing_cycle=data.billing_cycle,
            next_renewal=data.next_renewal,
            category=data.category,
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        return _sub_to_dict(sub)

    def update(self, db: Session, sub_id: str, user_id: str, data: UpdateSubscriptionRequest) -> dict:
        s = db.query(TrackedSubscription).filter(TrackedSubscription.id == sub_id).first()
        if not s:
            raise NotFoundError("Subscription not found")
        if str(s.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(s, field, value)
        db.commit()
        db.refresh(s)
        return _sub_to_dict(s)

    def delete(self, db: Session, sub_id: str, user_id: str) -> bool:
        s = db.query(TrackedSubscription).filter(TrackedSubscription.id == sub_id).first()
        if not s:
            raise NotFoundError("Subscription not found")
        if str(s.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        db.delete(s)
        db.commit()
        return True

    def get_renewals(self, db: Session, user_id: str, days: int = 30) -> List[dict]:
        today = date.today()
        cutoff = date.fromordinal(today.toordinal() + days)
        subs = (
            db.query(TrackedSubscription)
            .filter(
                TrackedSubscription.user_id == user_id,
                TrackedSubscription.is_active == True,
                TrackedSubscription.next_renewal != None,
                TrackedSubscription.next_renewal >= today,
                TrackedSubscription.next_renewal <= cutoff,
            )
            .order_by(TrackedSubscription.next_renewal.asc())
            .all()
        )
        return [_sub_to_dict(s) for s in subs]

    def get_total_monthly_cost(self, db: Session, user_id: str) -> dict:
        subs = (
            db.query(TrackedSubscription)
            .filter(
                TrackedSubscription.user_id == user_id,
                TrackedSubscription.is_active == True,
            )
            .all()
        )

        monthly_total = 0.0
        for s in subs:
            amount = float(s.amount)
            cycle = s.billing_cycle
            if cycle == "weekly":
                monthly_total += amount * 4.33
            elif cycle == "monthly":
                monthly_total += amount
            elif cycle == "yearly":
                monthly_total += amount / 12.0

        yearly_total = monthly_total * 12.0
        count = len(subs)

        return {
            "monthly_total": round(monthly_total, 2),
            "yearly_total": round(yearly_total, 2),
            "count": count,
        }
