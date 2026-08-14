import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Numeric, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class BillingPlan(Base):
    __tablename__ = "billing_plans"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    price_monthly = Column(Numeric(10, 2), nullable=True)
    price_yearly = Column(Numeric(10, 2), nullable=True)
    stripe_price_id_monthly = Column(String(255), nullable=True)
    stripe_price_id_yearly = Column(String(255), nullable=True)
    razorpay_plan_id = Column(String(255), nullable=True)
    features = Column(JSON, nullable=True)
    # Per-plan enforcement caps synced from the Control Hub (source of truth).
    caps = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    user_subscriptions = relationship("UserSubscription", back_populates="plan")


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    # unique=True (alembic 7f877195fa6b): one subscription row per user,
    # enforced at the DB layer to close a race two concurrent
    # /billing/subscribe calls could otherwise slip through — see
    # create_razorpay_subscription's IntegrityError handling.
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    plan_id = Column(UUID(as_uuid=False), ForeignKey("billing_plans.id", ondelete="SET NULL"), nullable=True)
    stripe_subscription_id = Column(String(255), unique=True, nullable=True)
    razorpay_subscription_id = Column(String(255), unique=True, nullable=True)
    gateway = Column(String(20), default="razorpay", nullable=False)  # razorpay | stripe
    # status values: trialing | active | past_due | halted | canceled | created
    status = Column(String(50), default="active", nullable=False)
    trial_end = Column(DateTime, nullable=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    # Set once report_purchase() to the Control Hub actually succeeds for
    # this row (best-effort call can silently fail — see
    # BillingService._report_purchase_to_hub). Null means the local
    # subscription exists but the Hub may not know about it yet; callers
    # use this to retry registration instead of assuming a single attempt
    # at webhook time was enough.
    hub_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="user_subscriptions")
    plan = relationship("BillingPlan", back_populates="user_subscriptions")
    payment_history = relationship("PaymentHistory", back_populates="subscription")
