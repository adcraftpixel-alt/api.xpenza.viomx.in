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
        # One-subscription-per-user, enforced at the DB layer (alembic
        # 7f877195fa6b) — closes a race where two concurrent /billing/subscribe
        # calls could both pass the app-level "already have a subscription"
        # check before either commits. Defensively de-duplicates first (keeps
        # the most recently created row per user) in case that race already
        # produced duplicates before this constraint existed.
        "DELETE FROM user_subscriptions a USING user_subscriptions b "
        "WHERE a.user_id = b.user_id AND a.created_at < b.created_at",
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conname = 'uq_user_subscriptions_user_id') THEN "
        "ALTER TABLE user_subscriptions ADD CONSTRAINT "
        "uq_user_subscriptions_user_id UNIQUE (user_id); "
        "END IF; END $$",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def check_schema_drift() -> list[str]:
    """
    Compare every mapped model's columns against what actually exists in the
    live DB and log/alert on any gap. Since prod's schema is hand-maintained
    via apply_schema_patches() rather than Alembic, a forgotten entry there
    (or a new model column) can silently 500 in prod for weeks with no alarm
    — this is exactly what happened with billing_plans.caps/razorpay_plan_id
    earlier this session. Non-fatal: never blocks startup.
    """
    import logging
    from sqlalchemy import inspect

    log = logging.getLogger(__name__)
    insp = inspect(engine)
    live_tables = set(insp.get_table_names())
    drift = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in live_tables:
            drift.append(f"{table_name}: table missing entirely")
            continue
        live_cols = {c["name"] for c in insp.get_columns(table_name)}
        model_cols = {c.name for c in table.columns}
        missing = model_cols - live_cols
        if missing:
            drift.append(f"{table_name}: missing columns {sorted(missing)}")

    if drift:
        detail = "\n".join(drift)
        log.error(
            "SCHEMA DRIFT DETECTED — models expect columns/tables the live "
            "DB doesn't have (add them to apply_schema_patches()):\n%s",
            detail,
        )
        try:
            from app.utils.email import send_email
            from app.config import settings
            send_email(
                to_email=settings.ADMIN_ALERT_EMAIL,
                subject="[Rupexi] Schema drift detected on startup",
                html_content=f"<pre>{detail}</pre>",
                plain_text=detail,
            )
        except Exception as e:
            log.error("Could not send schema-drift alert email: %s", e)

    return drift
