import logging
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.notification import Notification
from app.models.user_preference import UserPreference
from app.core.exceptions import NotFoundError, ForbiddenError
from app.api.v1.notifications.schemas import PreferencesRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _notif_to_dict(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "title": n.title,
        "body": n.body,
        "type": n.type,
        "is_read": n.is_read,
        "data": n.data,
        "created_at": str(n.created_at),
    }


_DUMMY_NOTIFICATIONS = [
    {
        "title": "Budget Alert",
        "body": "Food budget 80% used",
        "type": "budget_alert",
    },
    {
        "title": "Weekly Summary",
        "body": "You spent ₹45,680 this week",
        "type": "weekly",
    },
]


def _seed_dummy_notifications(db: Session, user_id: str) -> List[Notification]:
    """Insert default demo notifications for a new user and return them."""
    created = []
    for item in _DUMMY_NOTIFICATIONS:
        n = Notification(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=item["title"],
            body=item["body"],
            type=item["type"],
            is_read=False,
            data=None,
            created_at=datetime.utcnow(),
        )
        db.add(n)
        created.append(n)
    db.commit()
    for n in created:
        db.refresh(n)
    return created


# ---------------------------------------------------------------------------
# Default preference values (kept in one place for consistency)
# ---------------------------------------------------------------------------

_PREF_DEFAULTS = {
    "budget_alert": True,
    "large_expense_alert": True,
    "large_expense_threshold": 2000.0,
    "weekly_summary": True,
    "ai_tips": True,
    "notification_frequency": "daily",
    "ai_insights_enabled": True,
    "ai_savings_enabled": True,
    "ai_budget_prediction": True,
    "sms_reading_enabled": False,
    "theme": "light",
    "language": "en",
}


def _pref_to_dict(pref: Optional[UserPreference]) -> dict:
    """Build a full preferences dict, falling back to defaults for any missing field."""
    if pref is None:
        return dict(_PREF_DEFAULTS)

    # UserPreference doesn't have the new notification-specific boolean columns
    # so we store them in a lightweight JSON blob via pref.data if available,
    # or return sensible defaults merged with what the ORM model does carry.
    extra: dict = {}
    if hasattr(pref, "data") and isinstance(getattr(pref, "data", None), dict):
        extra = pref.data  # type: ignore[assignment]

    return {
        "budget_alert": extra.get("budget_alert", _PREF_DEFAULTS["budget_alert"]),
        "large_expense_alert": extra.get("large_expense_alert", _PREF_DEFAULTS["large_expense_alert"]),
        "large_expense_threshold": extra.get("large_expense_threshold", _PREF_DEFAULTS["large_expense_threshold"]),
        "weekly_summary": extra.get("weekly_summary", _PREF_DEFAULTS["weekly_summary"]),
        "ai_tips": extra.get("ai_tips", _PREF_DEFAULTS["ai_tips"]),
        "notification_frequency": pref.notification_frequency or _PREF_DEFAULTS["notification_frequency"],
        "ai_insights_enabled": pref.ai_insights_enabled,
        "ai_savings_enabled": pref.ai_savings_enabled,
        "ai_budget_prediction": pref.ai_budget_prediction,
        "sms_reading_enabled": pref.sms_reading_enabled,
        "theme": pref.theme or _PREF_DEFAULTS["theme"],
        "language": pref.language or _PREF_DEFAULTS["language"],
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class NotificationService:

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list(
        self,
        db: Session,
        user_id: str,
        unread_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Return paginated notifications for *user_id*.

        If the user has no notifications at all, seed two demo ones first.
        """
        query = db.query(Notification).filter(Notification.user_id == user_id)
        total_all = query.count()

        if total_all == 0:
            _seed_dummy_notifications(db, user_id)
            # Re-query after seeding
            query = db.query(Notification).filter(Notification.user_id == user_id)

        if unread_only:
            query = query.filter(Notification.is_read == False)  # noqa: E712

        total = query.count()
        notifs = (
            query.order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        unread_count = (
            db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
            .count()
        )

        return {
            "items": [_notif_to_dict(n) for n in notifs],
            "total": total,
            "unread_count": unread_count,
        }

    # ------------------------------------------------------------------
    # Mark read (single)
    # ------------------------------------------------------------------

    def mark_read(self, db: Session, notif_id: str, user_id: str) -> dict:
        n = db.query(Notification).filter(Notification.id == notif_id).first()
        if not n:
            raise NotFoundError("Notification not found")
        if str(n.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        n.is_read = True
        db.commit()
        db.refresh(n)
        return _notif_to_dict(n)

    # ------------------------------------------------------------------
    # Mark all read
    # ------------------------------------------------------------------

    def mark_all_read(self, db: Session, user_id: str) -> int:
        """Mark every unread notification as read.  Returns the count updated."""
        count = (
            db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
            .update({"is_read": True})
        )
        db.commit()
        return count

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, db: Session, notif_id: str, user_id: str) -> bool:
        n = db.query(Notification).filter(Notification.id == notif_id).first()
        if not n:
            raise NotFoundError("Notification not found")
        if str(n.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        db.delete(n)
        db.commit()
        return True

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def get_preferences(self, db: Session, user_id: str) -> dict:
        pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        return _pref_to_dict(pref)

    def update_preferences(self, db: Session, user_id: str, data: PreferencesRequest) -> dict:
        pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        if not pref:
            pref = UserPreference(user_id=user_id)
            db.add(pref)

        # Fields that exist on the ORM model — update directly
        orm_fields = {
            "notification_frequency",
            "ai_insights_enabled",
            "ai_savings_enabled",
            "ai_budget_prediction",
            "sms_reading_enabled",
            "theme",
            "language",
        }

        # Fields that are notification-specific extras — persisted in a JSON
        # blob if the model supports it, otherwise kept in-memory for response
        extra_fields = {
            "budget_alert",
            "large_expense_alert",
            "large_expense_threshold",
            "weekly_summary",
            "ai_tips",
        }

        payload = data.model_dump(exclude_unset=True)

        for field, value in payload.items():
            if field in orm_fields:
                setattr(pref, field, value)

        # Persist extra fields into pref.data JSON if the column exists
        if extra_fields.intersection(payload.keys()):
            current_extra: dict = {}
            if hasattr(pref, "data") and isinstance(getattr(pref, "data", None), dict):
                current_extra = dict(pref.data)  # type: ignore[assignment]
            for field in extra_fields:
                if field in payload:
                    current_extra[field] = payload[field]
            if hasattr(pref, "data"):
                pref.data = current_extra  # type: ignore[assignment]

        db.commit()
        db.refresh(pref)
        return _pref_to_dict(pref)

    # ------------------------------------------------------------------
    # Create notification (internal use by other services / Celery workers)
    # ------------------------------------------------------------------

    def create_notification(
        self,
        db: Session,
        user_id: str,
        title: str,
        body: str,
        type: str,  # noqa: A002  (shadows built-in, but matches spec)
        data: dict = {},  # noqa: B006
    ) -> dict:
        """Persist a new notification and return its dict representation."""
        n = Notification(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            body=body,
            type=type,
            is_read=False,
            data=data or None,
            created_at=datetime.utcnow(),
        )
        db.add(n)
        db.commit()
        db.refresh(n)
        logger.info("[NOTIFICATION] created id=%s user=%s type=%s", n.id, user_id, type)
        return _notif_to_dict(n)

    # ------------------------------------------------------------------
    # Device token (push notifications)
    # ------------------------------------------------------------------

    def register_device_token(
        self,
        user_id: str,
        token: str,
        platform: str,
        db: Session = None,
    ) -> bool:
        """Store device token in user_device_tokens table for push notifications."""
        if db is None:
            logger.info(
                "[PUSH TOKEN] user=%s platform=%s token=%s...", user_id, platform, token[:20]
            )
            return True
        try:
            db.execute(
                text(
                    """
                    INSERT INTO user_device_tokens (id, user_id, device_token, platform, created_at, updated_at)
                    VALUES (:id, :uid, :token, :platform, NOW(), NOW())
                    ON CONFLICT (user_id, device_token) DO UPDATE SET updated_at = NOW()
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "uid": user_id,
                    "token": token,
                    "platform": platform,
                },
            )
            db.commit()
            logger.info("[PUSH TOKEN] Registered: user=%s platform=%s", user_id, platform)
            return True
        except Exception as exc:
            logger.error("register_device_token failed: %s", exc)
            return False
