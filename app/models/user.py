import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Numeric, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=True, index=True)
    phone = Column(String(20), unique=True, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=True)
    user_type = Column(String(50), default="personal", nullable=False)
    monthly_income = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(10), default="INR", nullable=False)
    avatar_url = Column(Text, nullable=True)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    biometric_enabled = Column(Boolean, default=False, nullable=False)
    onboarding_done = Column(Boolean, default=False, nullable=False)
    stripe_customer_id = Column(String(255), nullable=True)
    firebase_uid = Column(String(255), nullable=True, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    preferences = relationship("UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="user", cascade="all, delete-orphan",
                           foreign_keys="[Expense.user_id]")
    budgets = relationship("Budget", back_populates="user", cascade="all, delete-orphan")
    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan")
    savings_goals = relationship("SavingsGoal", back_populates="user", cascade="all, delete-orphan")
    tracked_subscriptions = relationship("TrackedSubscription", back_populates="user", cascade="all, delete-orphan")
    ai_insights = relationship("AIInsight", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    user_subscriptions = relationship("UserSubscription", back_populates="user", cascade="all, delete-orphan")
    payment_history = relationship("PaymentHistory", back_populates="user", cascade="all, delete-orphan")
    chat_history = relationship("AIChatHistory", back_populates="user", cascade="all, delete-orphan")
    ocr_scans = relationship("OCRScan", back_populates="user", cascade="all, delete-orphan")
    wallets = relationship("Wallet", back_populates="user", cascade="all, delete-orphan")
