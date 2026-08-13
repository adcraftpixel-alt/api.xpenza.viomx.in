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
        "ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS "
        "month_start_day SMALLINT DEFAULT 1",
        # Family-group-wide financial cycle start day (mirrors the per-user
        # month_start_day but for the shared family book).
        "ALTER TABLE family_groups ADD COLUMN IF NOT EXISTS "
        "month_start_day SMALLINT DEFAULT 1",
        # Family expense spend attribution (who spent, vs user_id = who logged).
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS spent_by_user_id UUID",
        # Device tokens for push notifications. The model lives on a separate
        # Base, so create_all() never builds it — create it explicitly here.
        "CREATE TABLE IF NOT EXISTS user_device_tokens ("
        "  id UUID PRIMARY KEY,"
        "  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        "  device_token VARCHAR(512) NOT NULL,"
        "  platform VARCHAR(20) DEFAULT 'mobile',"
        "  created_at TIMESTAMP DEFAULT NOW(),"
        "  updated_at TIMESTAMP DEFAULT NOW(),"
        "  UNIQUE (user_id, device_token)"
        ")",
        "CREATE INDEX IF NOT EXISTS ix_user_device_tokens_user_id "
        "ON user_device_tokens (user_id)",
        # Razorpay recurring billing (alembic e5f6a7b8c9d0) — written as a real
        # migration but never applied to prod, since prod's schema is managed
        # here instead (see the crash-loop warning in Dockerfile). Mirrored
        # here so /billing/plans and /billing/subscribe stop 500ing.
        "ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS razorpay_plan_id VARCHAR(255)",
        "ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS "
        "razorpay_subscription_id VARCHAR(255)",
        "ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS "
        "gateway VARCHAR(20) NOT NULL DEFAULT 'razorpay'",
        "ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS trial_end TIMESTAMP",
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conname = 'uq_user_subscriptions_razorpay_subscription_id') THEN "
        "ALTER TABLE user_subscriptions ADD CONSTRAINT "
        "uq_user_subscriptions_razorpay_subscription_id "
        "UNIQUE (razorpay_subscription_id); "
        "END IF; END $$",
        "ALTER TABLE payment_history ADD COLUMN IF NOT EXISTS "
        "razorpay_invoice_id VARCHAR(255)",
        "ALTER TABLE payment_history ADD COLUMN IF NOT EXISTS "
        "razorpay_payment_id VARCHAR(255)",
        "ALTER TABLE payment_history ADD COLUMN IF NOT EXISTS gateway VARCHAR(20)",
        # Control Hub plan-cap enforcement (alembic f6a7b8c9d0e1) — same gap.
        "ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS caps JSONB",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
