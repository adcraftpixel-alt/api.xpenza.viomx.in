import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Numeric, DateTime, Date, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from app.database import Base


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(UUID(as_uuid=False), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), default="INR", nullable=False)
    description = Column(Text, nullable=True)
    merchant = Column(String(255), nullable=True)
    payment_method = Column(String(50), nullable=True)
    expense_date = Column(Date, nullable=False)
    is_recurring = Column(Boolean, default=False, nullable=False)
    recurring_interval = Column(String(50), nullable=True)
    receipt_url = Column(Text, nullable=True)
    tags = Column(ARRAY(String), nullable=True)
    source = Column(String(50), default="manual", nullable=False)
    ai_category = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    family_group_id = Column(UUID(as_uuid=False), ForeignKey("family_groups.id", ondelete="SET NULL"), nullable=True)
    added_by_user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Family expenses: the member the spend is ATTRIBUTED to (who spent), which
    # may differ from user_id/added_by (who logged it). Null => attributed to
    # user_id. Kept separate so edit/delete permissions still key off user_id.
    spent_by_user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="expenses", foreign_keys="[Expense.user_id]")
    category = relationship("Category", back_populates="expenses")
    ocr_scans = relationship("OCRScan", back_populates="expense")
