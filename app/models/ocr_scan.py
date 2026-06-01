import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class OCRScan(Base):
    __tablename__ = "ocr_scans"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    image_url = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)
    extracted_data = Column(JSON, nullable=True)
    expense_id = Column(UUID(as_uuid=False), ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="ocr_scans")
    expense = relationship("Expense", back_populates="ocr_scans")
