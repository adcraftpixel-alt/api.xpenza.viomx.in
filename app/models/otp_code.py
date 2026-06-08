import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class OtpCode(Base):
    """Durable OTP store — used as a fallback when Redis is unavailable.

    Auto-created by ``Base.metadata.create_all`` on startup (no migration).
    """
    __tablename__ = "otp_codes"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    identifier = Column(String(255), nullable=False)          # phone number or email
    purpose    = Column(String(30), nullable=False, default="login")  # login | pwd_reset
    code       = Column(String(10), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_otp_codes_identifier_purpose", "identifier", "purpose"),
    )
