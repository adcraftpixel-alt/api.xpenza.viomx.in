import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Numeric, DateTime, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class TrackedSubscription(Base):
    __tablename__ = "tracked_subscriptions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    billing_cycle = Column(String(50), default="monthly", nullable=False)
    next_renewal = Column(Date, nullable=True)
    category = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    detected_by_ai = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="tracked_subscriptions")
