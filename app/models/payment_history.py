import uuid
from datetime import datetime
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class PaymentHistory(Base):
    __tablename__ = "payment_history"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subscription_id = Column(UUID(as_uuid=False), ForeignKey("user_subscriptions.id", ondelete="SET NULL"), nullable=True)
    stripe_invoice_id = Column(String(255), nullable=True)
    stripe_payment_id = Column(String(255), nullable=True)
    razorpay_invoice_id = Column(String(255), nullable=True)
    razorpay_payment_id = Column(String(255), nullable=True)
    gateway = Column(String(20), nullable=True)  # razorpay | stripe
    method = Column(String(30), nullable=True)  # upi | card | netbanking | wallet
    amount = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(10), default="INR", nullable=False)
    status = Column(String(50), nullable=True)
    invoice_pdf_url = Column(String(512), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="payment_history")
    subscription = relationship("UserSubscription", back_populates="payment_history")
