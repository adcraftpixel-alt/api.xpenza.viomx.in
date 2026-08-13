from sqlalchemy import text

from app.database import Base, check_schema_drift, engine


def test_no_drift_on_a_freshly_created_schema():
    assert check_schema_drift() == []


def test_detects_a_missing_column_and_alerts(monkeypatch):
    emails = []
    monkeypatch.setattr(
        "app.utils.email.send_email",
        lambda **kwargs: emails.append(kwargs) or True,
    )

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE billing_plans DROP COLUMN caps"))
    try:
        drift = check_schema_drift()
    finally:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE billing_plans ADD COLUMN caps JSON"))

    assert any("billing_plans" in d and "caps" in d for d in drift)
    assert len(emails) == 1
    assert emails[0]["to_email"] == "superadmin@viomx.io"


def test_detects_a_missing_table(monkeypatch):
    # otp_codes is only imported lazily (inside auth/service.py functions), so
    # depending on test order it may not be in Base.metadata / the DB yet —
    # force it into existence first so this test doesn't depend on ordering.
    from app.models import otp_code  # noqa: F401
    Base.metadata.tables["otp_codes"].create(bind=engine, checkfirst=True)

    monkeypatch.setattr("app.utils.email.send_email", lambda **kwargs: True)

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE otp_codes CASCADE"))
    try:
        drift = check_schema_drift()
    finally:
        Base.metadata.tables["otp_codes"].create(bind=engine, checkfirst=True)

    assert any("otp_codes" in d and "missing entirely" in d for d in drift)
