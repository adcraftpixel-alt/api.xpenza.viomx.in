import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class CategoryKeyword(Base):
    """
    A data-driven keyword/alias that maps an item name to a category node.

    Examples (all pointing at the "Milk" leaf node):
        keyword="milk"  lang="en"
        keyword="doodh" lang="hi"
        keyword="dudh"  lang="hi"

    The hybrid categorizer matches an expense description against these rows
    first (fast, offline, free) before falling back to the LLM. User
    corrections are stored here too, so matching improves over time.
    """
    __tablename__ = "category_keywords"

    id          = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    category_id = Column(
        UUID(as_uuid=False), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    keyword     = Column(String(100), nullable=False)  # stored lowercase, normalized
    lang        = Column(String(10), nullable=True)     # en | hi | pa | ... (informational)
    source      = Column(String(20), nullable=False, default="seed")  # seed | learned | admin
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)

    category = relationship("Category", back_populates="keywords")
