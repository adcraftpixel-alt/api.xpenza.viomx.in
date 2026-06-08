from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    # Import all models so SQLAlchemy knows about them
    from app.models import (  # noqa: F401
        user, user_preference, category, category_keyword, expense, budget,
        savings_goal, subscription, ai_insight, notification,
        billing, payment_history, chat, ocr_scan, family_group, wallet,
        budget_month_amount, otp_code
    )
    Base.metadata.create_all(bind=engine)


def apply_schema_patches():
    """
    Idempotent schema patches for columns added to EXISTING tables.

    create_all() creates missing tables but never ALTERs existing ones, so new
    columns on already-created tables must be added explicitly. All statements
    are IF NOT EXISTS, so this is safe to run on every startup.
    """
    from sqlalchemy import text
    statements = [
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS family_group_id UUID",
        "CREATE INDEX IF NOT EXISTS ix_categories_family_group_id "
        "ON categories (family_group_id)",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
