"""Financial-cycle period helpers.

A user can set ``month_start_day`` (1-28) — e.g. salary on the 8th. A period
labelled (year, month) then runs from ``start_day`` of that month to the day
before ``start_day`` of the next month. start_day == 1 == a calendar month.

Use ``current_period_window`` / ``prev_period_window`` for "this month" logic
across the app so every feature follows the same cycle.
"""
from datetime import date, datetime, timedelta


def clamp_day(d) -> int:
    try:
        return max(1, min(28, int(d)))
    except (TypeError, ValueError):
        return 1


def next_month(y: int, m: int):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def prev_month(y: int, m: int):
    return (y - 1, 12) if m == 1 else (y, m - 1)


def get_month_start_day(db, user_id: str) -> int:
    """Read the user's configured cycle start day (default 1)."""
    try:
        from app.models.user_preference import UserPreference
        val = (
            db.query(UserPreference.month_start_day)
            .filter(UserPreference.user_id == str(user_id))
            .scalar()
        )
        return clamp_day(val) if val else 1
    except Exception:
        return 1


def get_group_month_start_day(db, group_id: str) -> int:
    """Cycle start day for a family group's shared book/analytics.

    The family cycle AUTO-FOLLOWS the group owner's (creator's) personal
    ``month_start_day`` — so the shared book always matches the creator's
    salary cycle, with no separate per-group setting to configure. Works for
    groups created before this behaviour existed (reads live from the owner's
    preference; no backfill needed).
    """
    try:
        from app.models.family_group import FamilyGroup
        created_by = (
            db.query(FamilyGroup.created_by)
            .filter(FamilyGroup.id == str(group_id))
            .scalar()
        )
        if not created_by:
            return 1
        return get_month_start_day(db, str(created_by))
    except Exception:
        return 1


def period_window(year: int, month: int, start_day: int):
    """(start_date, end_date) for the cycle labelled (year, month)."""
    sd = clamp_day(start_day)
    start = date(year, month, sd)
    ny, nm = next_month(year, month)
    end = date(ny, nm, sd) - timedelta(days=1)
    return start, end


def resolve_anchor(year: int, month: int, start_day: int, today: date):
    """When (year, month) is the current calendar month, snap to the cycle that
    actually contains today (handles the days before the start day)."""
    if year == today.year and month == today.month and today.day < clamp_day(start_day):
        return prev_month(year, month)
    return (year, month)


def current_period_window(db, user_id: str, today: date = None):
    """(start, end) of the cycle that contains today for this user."""
    today = today or datetime.utcnow().date()
    sd = get_month_start_day(db, user_id)
    ay, am = resolve_anchor(today.year, today.month, sd, today)
    return period_window(ay, am, sd)


def prev_period_window(db, user_id: str, today: date = None):
    """(start, end) of the cycle immediately before the current one."""
    today = today or datetime.utcnow().date()
    sd = get_month_start_day(db, user_id)
    ay, am = resolve_anchor(today.year, today.month, sd, today)
    py, pm = prev_month(ay, am)
    return period_window(py, pm, sd)
