import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_preference import UserPreference
from app.core.exceptions import NotFoundError, ConflictError
from app.api.v1.users.schemas import UpdateUserRequest, OnboardingRequest
from app.utils.storage import upload_to_s3, generate_unique_filename

logger = logging.getLogger(__name__)


class UserService:
    def get_me(self, user: User) -> dict:
        return {
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

    def upload_avatar(self, db: Session, user: User, file_bytes: bytes, filename: str) -> str:
        unique_name = f"avatars/{user.id}/{generate_unique_filename(filename)}"
        url = upload_to_s3(file_bytes, unique_name, "image/jpeg")
        user.avatar_url = url
        db.commit()
        return url

    def delete_account(self, db: Session, user: User) -> bool:
        db.delete(user)
        db.commit()
        return True
