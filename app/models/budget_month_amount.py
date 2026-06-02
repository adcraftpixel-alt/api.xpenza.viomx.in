import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class BudgetMonthAmount(Base):
    """Stores month-specific budget amounts (overrides per month/year)."""
    __tablename__ = "budget_month_amounts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    budget_id = Column(UUID(as_uuid=False), ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False)
    month = Column(Integer, nullable=False)   # 1–12
    year  = Column(Integer, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('budget_id', 'month', 'year', name='uq_budget_month_year'),
    )
