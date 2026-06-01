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
        user, user_preference, category, expense, budget,
        savings_goal, subscription, ai_insight, notification,
        billing, payment_history, chat, ocr_scan, family_group, wallet
    )
    Base.metadata.create_all(bind=engine)
