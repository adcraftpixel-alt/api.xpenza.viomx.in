"""
Admin seed script — creates a superadmin user for the admin panel.
Run: cd backend && .venv/bin/python seed_admin.py

To change credentials, set env vars before running:
  ADMIN_EMAIL=you@example.com ADMIN_PASSWORD=YourPass123 .venv/bin/python seed_admin.py
"""
import os
import uuid
from datetime import datetime

from app.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.models.user_preference import UserPreference

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@rupexi.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@1234")
ADMIN_NAME = os.getenv("ADMIN_NAME", "Super Admin")

db = SessionLocal()

existing = db.query(User).filter(User.email == ADMIN_EMAIL).first()

if existing:
    if existing.user_type != "admin":
        existing.user_type = "admin"
        existing.is_verified = True
        existing.is_active = True
        db.commit()
        print(f"Updated existing user to admin: {ADMIN_EMAIL}")
    else:
        print(f"Admin user already exists: {ADMIN_EMAIL}")
else:
    admin = User(
        id=str(uuid.uuid4()),
        name=ADMIN_NAME,
        email=ADMIN_EMAIL,
        password_hash=hash_password(ADMIN_PASSWORD),
        user_type="admin",
        currency="INR",
        is_verified=True,
        is_active=True,
        onboarding_done=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(admin)
    db.flush()

    db.add(UserPreference(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        notification_frequency="daily",
        ai_insights_enabled=True,
        ai_savings_enabled=True,
        ai_budget_prediction=True,
        theme="light",
    ))

    db.commit()
    print(f"Created admin user: {ADMIN_EMAIL}")

db.close()

print()
print("=" * 40)
print("  Admin Panel Credentials")
print("=" * 40)
print(f"  URL:      http://localhost:5177")
print(f"  Email:    {ADMIN_EMAIL}")
print(f"  Password: {ADMIN_PASSWORD}")
print("=" * 40)
