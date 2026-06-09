from sqlalchemy.orm import Session
from app.models.user_preference import UserPreference


_DEFAULTS = {
    "notification_frequency": "daily",
    "ai_insights_enabled": True,
    "ai_savings_enabled": True,
    "ai_budget_prediction": True,
    "sms_reading_enabled": False,
    "theme": "light",
    "language": "en",
    "month_start_day": 1,
}


def _row_to_dict(pref: UserPreference) -> dict:
    return {
        "id": pref.id,
        "user_id": pref.user_id,
        "notification_frequency": pref.notification_frequency,
        "ai_insights_enabled": pref.ai_insights_enabled,
        "ai_savings_enabled": pref.ai_savings_enabled,
        "ai_budget_prediction": pref.ai_budget_prediction,
        "sms_reading_enabled": pref.sms_reading_enabled,
        "theme": pref.theme,
        "language": pref.language,
        "month_start_day": getattr(pref, "month_start_day", 1) or 1,
        "created_at": pref.created_at.isoformat() if pref.created_at else None,
    }


class PreferencesService:
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch(self, db: Session, user_id: str) -> UserPreference | None:
        return (
            db.query(UserPreference)
            .filter(UserPreference.user_id == str(user_id))
            .first()
        )

    def _create_defaults(self, db: Session, user_id: str) -> UserPreference:
        pref = UserPreference(user_id=str(user_id), **_DEFAULTS)
        db.add(pref)
        db.commit()
        db.refresh(pref)
        return pref

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, db: Session, user_id: str) -> dict | None:
        """Return preferences as a dict, or None if the row does not exist."""
        pref = self._fetch(db, user_id)
        if pref is None:
            return None
        return _row_to_dict(pref)

    def get_with_defaults(self, db: Session, user_id: str) -> dict:
        """Return preferences, creating a default row when one does not exist."""
        pref = self._fetch(db, user_id)
        if pref is None:
            pref = self._create_defaults(db, user_id)
        return _row_to_dict(pref)

    def update(self, db: Session, user_id: str, data: dict) -> dict:
        """
        Partial-update preferences from *data* (a dict of changed fields).
        Creates the row with defaults first if it does not exist.
        """
        pref = self._fetch(db, user_id)
        if pref is None:
            pref = self._create_defaults(db, user_id)

        allowed = {
            "notification_frequency",
            "ai_insights_enabled",
            "ai_savings_enabled",
            "ai_budget_prediction",
            "sms_reading_enabled",
            "theme",
            "language",
            "month_start_day",
        }

        for field, value in data.items():
            if field in allowed and value is not None:
                # Clamp the cycle start day to a safe range (avoid 29-31 which
                # don't exist in every month).
                if field == "month_start_day":
                    try:
                        value = max(1, min(28, int(value)))
                    except (TypeError, ValueError):
                        continue
                setattr(pref, field, value)

        db.commit()
        db.refresh(pref)
        return _row_to_dict(pref)
