from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.models.user import User
from app.api.v1.analytics.service import analytics_service
from app.utils.response import success

router = APIRouter(tags=["Analytics"])


@router.get("/monthly")
def get_monthly(
    month: str = Query(default=None, description="YYYY-MM format"),
    months: int = Query(default=1, ge=1, le=24, description="Number of months to return as trend list"),
    shared: bool = Query(default=False, description="True = family-pooled, False = personal"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    If months > 1: returns a list of monthly totals (for dashboard chips).
    If months == 1: returns detailed single-month breakdown.
    """
    now = datetime.utcnow()
    # If month param given OR months==1 with no explicit month, use single-month detail
    # Only return list when months > 1 (for dashboard trend chips)
    if months > 1 and month is None:
        from sqlalchemy import func
        from app.models.expense import Expense
        from app.utils.period import (
            get_month_start_day, period_window, resolve_anchor, prev_month,
        )
        start_day = get_month_start_day(db, str(current_user.id))
        cy, cm = resolve_anchor(now.year, now.month, start_day, now.date())
        result = []
        month_names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        for i in range(months - 1, -1, -1):
            ty, tm = cy, cm
            for _ in range(i):
                ty, tm = prev_month(ty, tm)
            win_start, win_end = period_window(ty, tm, start_day)
            total = db.query(func.sum(Expense.amount)).filter(
                Expense.user_id == str(current_user.id),
                Expense.expense_date >= win_start,
                Expense.expense_date <= win_end,
            ).scalar() or 0.0
            result.append({
                'month': month_names[tm],
                'month_num': tm,
                'year': ty,
                'total': float(total),
                'total_expense': float(total),
            })
        return success(result)

    if not month:
        month = f"{now.year}-{now.month:02d}"
    data = analytics_service.get_monthly(str(current_user.id), month, db, shared=shared)
    return success(data)


@router.get("/categories")
def get_categories(
    month: int = Query(default=None, ge=1, le=12, description="Month number (1-12)"),
    year: int = Query(default=None, description="4-digit year"),
    # Legacy date-range params kept for backwards compatibility
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    now = datetime.utcnow()
    # If month/year params are provided, use the new ai_category grouping
    if month is not None or year is not None:
        mo = month if month is not None else now.month
        yr = year if year is not None else now.year
        data = analytics_service.get_categories_by_month(str(current_user.id), mo, yr, db)
        return success(data)
    # Fallback: legacy date-range behaviour
    if not start_date:
        start_date = f"{now.year}-{now.month:02d}-01"
    if not end_date:
        end_date = now.strftime("%Y-%m-%d")
    data = analytics_service.get_categories(str(current_user.id), start_date, end_date, db)
    return success(data)


@router.get("/category-breakdown")
def get_category_breakdown(
    month: int = Query(default=None, ge=1, le=12, description="Month number (1-12)"),
    year: int = Query(default=None, description="4-digit year"),
    shared: bool = Query(default=False, description="True = family-pooled, False = personal"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Monthly spend rolled up the category tree into category → sub-category."""
    now = datetime.utcnow()
    mo = month if month is not None else now.month
    yr = year if year is not None else now.year
    data = analytics_service.get_category_breakdown(str(current_user.id), mo, yr, db, shared=shared)
    return success(data)


@router.get("/income-vs-expense")
def get_income_vs_expense(
    months: int = Query(default=6, ge=1, le=24),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    data = analytics_service.get_income_vs_expense_summary(str(current_user.id), months, db)
    return success(data)


@router.get("/yearly")
def get_yearly(
    year: int = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    if not year:
        year = datetime.utcnow().year
    data = analytics_service.get_yearly(str(current_user.id), year, db)
    return success(data)


@router.get("/payment-methods")
def get_payment_methods(
    month: str = Query(default=None),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    if not month:
        now = datetime.utcnow()
        month = f"{now.year}-{now.month:02d}"
    data = analytics_service.get_payment_methods(str(current_user.id), month, db)
    return success(data)
