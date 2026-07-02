import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Numeric, SmallInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class FamilyGroup(Base):
    __tablename__ = "family_groups"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Day of month the family's shared financial cycle starts (e.g. the main
    # earner's salary day). 1 = a normal calendar month. Group-wide setting so
    # the whole family book/analytics follow the same cycle — independent of any
    # member's personal month_start_day preference.
    month_start_day = Column(SmallInteger, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    members = relationship("FamilyGroupMember", back_populates="group", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])


class FamilyGroupMember(Base):
    __tablename__ = "family_group_members"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    group_id = Column(UUID(as_uuid=False), ForeignKey("family_groups.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    phone = Column(String(20), nullable=False)
    name = Column(String(100), nullable=True)
    role = Column(String(20), default="member", nullable=False)  # admin | member
    status = Column(String(20), default="pending", nullable=False)  # pending | accepted
    contribution = Column(Numeric(12, 2), default=0, nullable=False)  # amount this member adds to the household pool
    invited_by = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    joined_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    group = relationship("FamilyGroup", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
    inviter = relationship("User", foreign_keys=[invited_by])
