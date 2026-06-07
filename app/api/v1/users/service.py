import logging
from datetime import date
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_preference import UserPreference
from app.models.expense import Expense
from app.models.savings_goal import SavingsGoal
from app.core.exceptions import NotFoundError, ConflictError
from app.api.v1.users.schemas import UpdateUserRequest, OnboardingRequest
from app.utils.storage import upload_to_s3, generate_unique_filename

logger = logging.getLogger(__name__)


def _resize_avatar(data: bytes) -> bytes:
    """Shrink the avatar to a small square JPEG so it stays tiny regardless of
    client (image_picker's resize is a no-op on web). Returns the original
    bytes if the image can't be processed."""
    try:
        from io import BytesIO
        from PIL import Image

        img = Image.open(BytesIO(data)).convert("RGB")
        img.thumbnail((512, 512))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Avatar resize failed, storing original: %s", exc)
        return data

logger = logging.getLogger(__name__)


class UserService:
    def get_me(self, user: User, db: Optional[Session] = None) -> dict:
        data = {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "user_type": user.user_type,
            "monthly_income": float(user.monthly_income) if user.monthly_income else None,
            "currency": user.currency,
            "avatar_url": user.avatar_url,
            "is_verified": user.is_verified,
            "is_active": user.is_active,
            "onboarding_done": user.onboarding_done,
            "biometric_enabled": user.biometric_enabled,
            "created_at": str(user.created_at) if user.created_at else None,
        }
        if db is not None:
            data.update(self._profile_stats(db, str(user.id)))
        return data

    def _profile_stats(self, db: Session, user_id: str) -> dict:
        """Personal-scope spending stats shown on the profile header."""
        # Personal expenses only (exclude shared family expenses)
        base = db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.family_group_id.is_(None),
        )
        total_spent = db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
            Expense.user_id == user_id, Expense.family_group_id.is_(None),
        ).scalar() or 0
        month_start = date.today().replace(day=1)
        this_month = db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
            Expense.user_id == user_id,
            Expense.family_group_id.is_(None),
            Expense.expense_date >= month_start,
        ).scalar() or 0
        expense_count = base.count()
        # Savings = total put aside across the user's savings goals
        savings = db.query(func.coalesce(func.sum(SavingsGoal.current_amount), 0)).filter(
            SavingsGoal.user_id == user_id,
        ).scalar() or 0
        return {
            "total_spent": float(total_spent),
            "this_month_spent": float(this_month),
            "expense_count": int(expense_count),
            "savings": float(savings),
        }

    def update_me(self, db: Session, user: User, data: UpdateUserRequest) -> User:
        if data.name is not None:
            user.name = data.name
        if data.phone is not None:
            existing = db.query(User).filter(User.phone == data.phone, User.id != user.id).first()
            if existing:
                raise ConflictError("Phone number already in use")
            user.phone = data.phone
        if data.monthly_income is not None:
            user.monthly_income = data.monthly_income
        if data.currency is not None:
            user.currency = data.currency
        if data.biometric_enabled is not None:
            user.biometric_enabled = data.biometric_enabled
        if data.user_type is not None:
            user.user_type = data.user_type
        if data.onboarding_done is not None:
            user.onboarding_done = data.onboarding_done
        if data.avatar_url is not None:
            user.avatar_url = data.avatar_url
        db.commit()
        db.refresh(user)
        return user

    def complete_onboarding(self, db: Session, user: User, data: OnboardingRequest) -> User:
        user.user_type = data.user_type
        user.monthly_income = data.monthly_income
        user.currency = data.currency
        user.onboarding_done = True

        # Update preferences
        pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
        if not pref:
            pref = UserPreference(user_id=user.id)
            db.add(pref)
        pref.notification_frequency = data.notification_frequency
        pref.ai_insights_enabled = data.ai_insights_enabled
        pref.sms_reading_enabled = data.sms_reading_enabled

        # New onboarding fields — guarded in case DB column not yet migrated
        if hasattr(pref, "income_type"):
            pref.income_type = data.income_type
        if hasattr(pref, "payment_methods"):
            pref.payment_methods = data.payment_methods
        if hasattr(pref, "alert_threshold"):
            pref.alert_threshold = data.alert_threshold
        if hasattr(pref, "pain_point"):
            pref.pain_point = data.pain_point

        db.commit()

        # Seed the canonical 3-level default tree + keyword aliases (personal scope).
        # Idempotent — attaches sub-trees under any existing roots without duplicating.
        from app.api.v1.categories.default_tree import seed_category_tree
        seed_category_tree(db, user_id=str(user.id), family_group_id=None)

        db.refresh(user)
        return user

    def upload_avatar(
        self,
        db: Session,
        user: User,
        file_bytes: bytes,
        filename: str,
        base_url: Optional[str] = None,
    ) -> str:
        # Compress/resize server-side so the stored avatar is always small.
        file_bytes = _resize_avatar(file_bytes)
        unique_name = f"avatars/{user.id}/{generate_unique_filename('avatar.jpg')}"
        url = upload_to_s3(file_bytes, unique_name, "image/jpeg")
        # Local fallback returns a relative path; make it absolute so the app
        # can load it directly via NetworkImage.
        if url.startswith("/") and base_url:
            url = base_url.rstrip("/") + url
        user.avatar_url = url
        db.commit()
        return url

    def delete_account(self, db: Session, user: User) -> bool:
        db.delete(user)
        db.commit()
        return True
