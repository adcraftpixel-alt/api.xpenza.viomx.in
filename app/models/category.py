import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, SmallInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Category(Base):
    __tablename__ = "categories"

    id         = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    parent_id  = Column(UUID(as_uuid=False), ForeignKey("categories.id", ondelete="CASCADE"), nullable=True)
    name       = Column(String(100), nullable=False)
    icon       = Column(String(100), nullable=True)
    color      = Column(String(20),  nullable=True)
    level      = Column(SmallInteger(), nullable=False, default=0)  # 0=root 1=sub-parent 2=child
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user     = relationship("User", back_populates="categories")
    expenses = relationship("Expense", back_populates="category")
    budgets  = relationship("Budget", back_populates="category")

    # Self-referential tree (adjacency list)
    children = relationship(
        "Category",
        back_populates="parent_cat",
        foreign_keys=[parent_id],
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent_cat = relationship(
        "Category",
        back_populates="children",
        foreign_keys=[parent_id],
        remote_side="Category.id",
        lazy="select",
    )
