import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, SmallInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    notification_frequency = Column(String(50), default="daily", nullable=False)
    ai_insights_enabled = Column(Boolean, default=True, nullable=False)
    ai_savings_enabled = Column(Boolean, default=True, nullable=False)
    ai_budget_prediction = Column(Boolean, default=True, nullable=False)
    sms_reading_enabled = Column(Boolean, default=False, nullable=False)
    theme = Column(String(20), default="light", nullable=False)
    language = Column(String(10), default="en", nullable=False)
    # Day of month the user's financial cycle starts (e.g. salary day). 1 = a
    # normal calendar month. Used to compute analytics period windows.
    month_start_day = Column(SmallInteger, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="preferences")
