import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Numeric, DateTime, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(UUID(as_uuid=False), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    spent = Column(Numeric(12, 2), default=0, nullable=False)
    period = Column(String(50), default="monthly", nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    alert_threshold = Column(Numeric(5, 2), default=80.00, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_shared = Column(Boolean, default=False, nullable=False)
    family_group_id = Column(UUID(as_uuid=False), ForeignKey("family_groups.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="budgets")
    category = relationship("Category", back_populates="budgets")
