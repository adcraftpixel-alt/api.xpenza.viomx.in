import math
import logging
from datetime import date
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.user import User
from app.models.expense import Expense
from app.models.notification import Notification
from app.models.billing import BillingPlan, UserSubscription
from app.core.exceptions import NotFoundError
from app.api.v1.admin.schemas import BroadcastNotificationRequest, UpdateUserPlanRequest

logger = logging.getLogger(__name__)


def _user_to_dict(u: User) -> dict:
    return {
        "id": str(u.id),
        "name": u.name,
        "email": u.email,
        "phone": u.phone,
        "user_type": u.user_type,
        "is_active": u.is_active,
        "is_verified": u.is_verified,
        "onboarding_done": u.onboarding_done,
        "created_at": str(u.created_at),
    }


class AdminService:
    def get_stats(self, db: Session) -> dict:
        total_users = db.query(func.count(User.id)).scalar() or 0
        active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0
        total_expenses = db.query(func.count(Expense.id)).scalar() or 0
        total_amount = float(db.query(func.sum(Expense.amount)).scalar() or 0)

        today = date.today()
        month_start = today.replace(day=1)
        new_users = db.query(func.count(User.id)).filter(User.created_at >= month_start).scalar() or 0

        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_expenses": total_expenses,
            "total_amount_tracked": total_amount,
            "new_users_this_month": new_users,
        }

    def list_users(self, db: Session, page: int = 1, page_size: int = 20, search: Optional[str] = None) -> dict:
        query = db.query(User)
        if search:
            from sqlalchemy import or_
            query = query.filter(
                or_(User.name.ilike(f"%{search}%"), User.email.ilike(f"%{search}%"))
            )
        total = query.count()
        users = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {
            "items": [_user_to_dict(u) for u in users],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total > 0 else 0,
        }

    def get_user(self, db: Session, user_id: str) -> dict:
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            raise NotFoundError("User not found")
        return _user_to_dict(u)

    def update_user_plan(self, db: Session, user_id: str, data: UpdateUserPlanRequest) -> bool:
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            raise NotFoundError("User not found")
        plan = db.query(BillingPlan).filter(BillingPlan.name == data.plan_name).first()
        if not plan:
            raise NotFoundError(f"Plan '{data.plan_name}' not found")

        sub = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()
        if sub:
            sub.plan_id = plan.id
            sub.status = "active"
        else:
            sub = UserSubscription(user_id=user_id, plan_id=plan.id, status="active")
            db.add(sub)
        db.commit()
        return True

    def suspend_user(self, db: Session, user_id: str) -> bool:
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            raise NotFoundError("User not found")
        u.is_active = False
        db.commit()
        return True

    def activate_user(self, db: Session, user_id: str) -> bool:
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            raise NotFoundError("User not found")
        u.is_active = True
        db.commit()
        return True

    def delete_user(self, db: Session, user_id: str) -> bool:
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            raise NotFoundError("User not found")
        db.delete(u)
        db.commit()
        return True

    def get_billing_overview(self, db: Session) -> dict:
        from app.models.billing import UserSubscription
        total_subs = db.query(func.count(UserSubscription.id)).filter(UserSubscription.status == "active").scalar() or 0
        plan_dist = db.execute(
            __import__("sqlalchemy").text("""
                SELECT bp.name, COUNT(us.id) as count
                FROM user_subscriptions us
                JOIN billing_plans bp ON bp.id = us.plan_id
                WHERE us.status = 'active'
                GROUP BY bp.name ORDER BY count DESC
            """)
        ).fetchall()
        monthly_revenue = db.execute(
            __import__("sqlalchemy").text("""
                SELECT COALESCE(SUM(bp.price_monthly), 0) as revenue
                FROM user_subscriptions us
                JOIN billing_plans bp ON bp.id = us.plan_id
                WHERE us.status = 'active' AND bp.price_monthly IS NOT NULL
            """)
        ).fetchone()
        return {
            "active_subscriptions": total_subs,
            "monthly_recurring_revenue": float(monthly_revenue.revenue) if monthly_revenue else 0,
            "plan_distribution": [{"plan": r.name, "count": r.count} for r in plan_dist],
        }

    def list_subscriptions(self, db: Session, page: int = 1, page_size: int = 20) -> dict:
        from app.models.billing import UserSubscription
        total = db.query(func.count(UserSubscription.id)).scalar() or 0
        rows = db.execute(
            __import__("sqlalchemy").text("""
                SELECT us.id, u.name, u.email, bp.name as plan, us.status,
                       us.created_at, us.cancel_at_period_end
                FROM user_subscriptions us
                JOIN users u ON u.id = us.user_id
                JOIN billing_plans bp ON bp.id = us.plan_id
                ORDER BY us.created_at DESC
                LIMIT :lim OFFSET :off
            """),
            {"lim": page_size, "off": (page - 1) * page_size},
        ).fetchall()
        return {
            "items": [{"id": str(r.id), "user_name": r.name, "email": r.email, "plan": r.plan, "status": r.status, "cancel_at_period_end": r.cancel_at_period_end, "created_at": str(r.created_at)} for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total > 0 else 0,
        }

    def get_revenue_analytics(self, db: Session, months: int = 6) -> list:
        rows = db.execute(
            __import__("sqlalchemy").text("""
                SELECT DATE_TRUNC('month', created_at) as month,
                       COUNT(*) as new_subs,
                       COALESCE(SUM(ph.amount), 0) as revenue
                FROM user_subscriptions us
                LEFT JOIN payment_history ph ON ph.user_id = us.user_id
                    AND DATE_TRUNC('month', ph.created_at) = DATE_TRUNC('month', us.created_at)
                WHERE us.created_at >= NOW() - INTERVAL ':m months'
                GROUP BY DATE_TRUNC('month', created_at)
                ORDER BY month
            """.replace(":m months", f"{months} months"))
        ).fetchall()
        return [{"month": str(r.month)[:7], "new_subscriptions": r.new_subs, "revenue": float(r.revenue)} for r in rows]

    def get_usage_analytics(self, db: Session) -> dict:
        today = date.today()
        month_start = today.replace(day=1)
        dau = db.execute(
            __import__("sqlalchemy").text("""
                SELECT COUNT(DISTINCT user_id) FROM expenses WHERE expense_date = :today
            """),
            {"today": today},
        ).scalar() or 0
        mau = db.execute(
            __import__("sqlalchemy").text("""
                SELECT COUNT(DISTINCT user_id) FROM expenses WHERE expense_date >= :start
            """),
            {"start": month_start},
        ).scalar() or 0
        top_categories = db.execute(
            __import__("sqlalchemy").text("""
                SELECT COALESCE(c.name, 'Uncategorized'), COUNT(e.id) as cnt
                FROM expenses e LEFT JOIN categories c ON c.id = e.category_id
                GROUP BY c.name ORDER BY cnt DESC LIMIT 5
            """)
        ).fetchall()
        return {
            "dau": dau,
            "mau": mau,
            "top_categories": [{"name": r[0], "count": r[1]} for r in top_categories],
        }

    def broadcast_notification(self, db: Session, data: BroadcastNotificationRequest) -> int:
        query = db.query(User).filter(User.is_active == True)
        if data.target == "verified":
            query = query.filter(User.is_verified == True)
        elif data.target == "unverified":
            query = query.filter(User.is_verified == False)

        users = query.all()
        count = 0
        for u in users:
            notif = Notification(
                user_id=u.id,
                title=data.title,
                body=data.body,
                type=data.type,
            )
            db.add(notif)
            count += 1
        db.commit()
        logger.info(f"Broadcast notification sent to {count} users")
        return count
