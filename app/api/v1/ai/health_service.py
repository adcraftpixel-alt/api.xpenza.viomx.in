"""
health_service.py — Standalone AI health, prediction, and subscription-detection functions.

Each function is a pure data-layer operation (no class required) so they can be
called directly from the router or composed into other services.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.budget import Budget
from app.models.expense import Expense
from app.models.savings_goal import SavingsGoal
from app.models.subscription import TrackedSubscription

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# get_health_score
# ---------------------------------------------------------------------------

def get_health_score(db: Session, user_id: str, user: Any | None = None) -> dict:
    """
    Calculate a financial health score from 0-100.

    Scoring breakdown (100 pts total):
      - savings_rate        : up to 40 pts  (income - expenses) / income
      - budget_adherence    : up to 30 pts  % of active budgets not exceeded
      - expense_consistency : up to 30 pts  inverse of monthly spending variance

    Returns:
        {
            score      : int,
            grade      : str,          # A/B/C/D/F
            breakdown  : dict,         # per-component detail
            trend      : str,          # improving / stable / declining
            tips       : list[str],
        }
    """
    today = date.today()
    month_start = today.replace(day=1)
    tips: list[str] = []
    breakdown: dict[str, Any] = {}

    # ---- savings_rate (0–40 pts) ----------------------------------------
    savings_pts = 0
    income = float(user.monthly_income) if (user and user.monthly_income) else 0.0

    total_spent_this_month = float(
        db.query(func.sum(Expense.amount))
        .filter(
            Expense.user_id == user_id,
            Expense.expense_date >= month_start,
        )
        .scalar() or 0
    )

    if income > 0:
        savings = income - total_spent_this_month
        savings_rate = savings / income
        # Scale: 20 %+ savings => full 40 pts; 0 % => 0 pts
        savings_pts = max(0, min(40, int(savings_rate * 200)))
        breakdown["savings_rate"] = {
            "score": savings_pts,
            "max": 40,
            "rate_pct": round(savings_rate * 100, 1),
            "income": income,
            "spent": total_spent_this_month,
        }
        if savings_rate < 0:
            tips.append("You are overspending this month — cut non-essential expenses immediately.")
        elif savings_rate < 0.10:
            tips.append("Try to save at least 10% of your income each month.")
        elif savings_rate < 0.20:
            tips.append("Good start! Aim for a 20%+ savings rate for long-term security.")
    else:
        breakdown["savings_rate"] = {
            "score": 0,
            "max": 40,
            "note": "Monthly income not set",
        }
        tips.append("Set your monthly income to unlock savings-rate tracking.")

    # ---- budget_adherence (0–30 pts) ------------------------------------
    budgets = (
        db.query(Budget)
        .filter(Budget.user_id == user_id, Budget.is_active == True)
        .all()
    )
    if budgets:
        within = sum(1 for b in budgets if float(b.spent) <= float(b.amount))
        budget_pts = int((within / len(budgets)) * 30)
        breakdown["budget_adherence"] = {
            "score": budget_pts,
            "max": 30,
            "within_budget": within,
            "total_budgets": len(budgets),
        }
        if budget_pts < 15:
            tips.append("You are exceeding more than half your budgets — review your limits.")
    else:
        budget_pts = 0
        breakdown["budget_adherence"] = {
            "score": 0,
            "max": 30,
            "note": "No active budgets set",
        }
        tips.append("Create category budgets to take control of your spending.")

    # ---- expense_consistency (0–30 pts) ---------------------------------
    # Compare last 3 months of spending; lower coefficient-of-variation => higher score.
    monthly_totals: list[float] = []
    for i in range(1, 4):
        ref_month = today.month - i
        ref_year = today.year
        if ref_month <= 0:
            ref_month += 12
            ref_year -= 1
        m_start = today.replace(year=ref_year, month=ref_month, day=1)
        next_month = ref_month + 1
        next_year = ref_year
        if next_month > 12:
            next_month = 1
            next_year += 1
        m_end = today.replace(year=next_year, month=next_month, day=1)

        total = float(
            db.query(func.sum(Expense.amount))
            .filter(
                Expense.user_id == user_id,
                Expense.expense_date >= m_start,
                Expense.expense_date < m_end,
            )
            .scalar() or 0
        )
        monthly_totals.append(total)

    if any(t > 0 for t in monthly_totals):
        avg = sum(monthly_totals) / len(monthly_totals)
        variance = sum((t - avg) ** 2 for t in monthly_totals) / len(monthly_totals)
        std_dev = variance ** 0.5
        cv = std_dev / avg if avg > 0 else 1.0          # coefficient of variation
        # cv 0 => 30 pts; cv >= 1 => 0 pts
        consistency_pts = max(0, min(30, int((1 - min(cv, 1.0)) * 30)))
    else:
        consistency_pts = 0

    breakdown["expense_consistency"] = {
        "score": consistency_pts,
        "max": 30,
        "monthly_totals": list(reversed(monthly_totals)),
    }
    if consistency_pts < 10:
        tips.append("Your monthly spending fluctuates a lot — try to maintain consistent habits.")

    # ---- aggregate -------------------------------------------------------
    total_score = min(100, savings_pts + budget_pts + consistency_pts)
    grade = (
        "A" if total_score >= 80
        else "B" if total_score >= 65
        else "C" if total_score >= 50
        else "D" if total_score >= 35
        else "F"
    )

    # Simple trend: compare this month's score with last month's estimate
    trend = "stable"
    if monthly_totals and income > 0:
        last_month_spent = monthly_totals[0]
        if last_month_spent > total_spent_this_month * 1.1:
            trend = "improving"
        elif last_month_spent < total_spent_this_month * 0.9:
            trend = "declining"

    return {
        "score": total_score,
        "grade": grade,
        "breakdown": breakdown,
        "trend": trend,
        "tips": tips or ["Keep it up — you are on track!"],
    }


# ---------------------------------------------------------------------------
# get_predictions
# ---------------------------------------------------------------------------

def get_predictions(db: Session, user_id: str) -> dict:
    """
    Predict next month's spend using a 3-month simple moving average.

    Returns:
        {
            next_month_spend    : float,
            savings_estimate    : float | None,
            top_category        : str | None,
            forecast            : list[{month, predicted, actual}],
            trend               : str,   # increasing / decreasing / stable
            confidence          : float, # 0–1
        }
    """
    today = date.today()
    monthly_totals: list[float] = []
    forecast: list[dict] = []

    for i in range(1, 4):
        ref_month = today.month - i
        ref_year = today.year
        if ref_month <= 0:
            ref_month += 12
            ref_year -= 1
        m_start = today.replace(year=ref_year, month=ref_month, day=1)
        next_m = ref_month + 1
        next_y = ref_year
        if next_m > 12:
            next_m = 1
            next_y += 1
        m_end = today.replace(year=next_y, month=next_m, day=1)

        actual = float(
            db.query(func.sum(Expense.amount))
            .filter(
                Expense.user_id == user_id,
                Expense.expense_date >= m_start,
                Expense.expense_date < m_end,
            )
            .scalar() or 0
        )
        monthly_totals.append(actual)
        forecast.append({"month": f"{ref_year}-{ref_month:02d}", "actual": round(actual, 2)})

    forecast = list(reversed(forecast))       # chronological order

    avg_spend = sum(monthly_totals) / len(monthly_totals) if monthly_totals else 0.0
    round_avg = round(avg_spend, 2)

    # Trend
    trend = "stable"
    if len(monthly_totals) >= 2 and monthly_totals[1] > 0:
        if monthly_totals[0] > monthly_totals[1] * 1.10:
            trend = "increasing"
        elif monthly_totals[0] < monthly_totals[1] * 0.90:
            trend = "decreasing"

    # Top category for current month
    top_cat_row = (
        db.query(Expense.ai_category, func.sum(Expense.amount).label("total"))
        .filter(
            Expense.user_id == user_id,
            Expense.expense_date >= today.replace(day=1),
        )
        .group_by(Expense.ai_category)
        .order_by(func.sum(Expense.amount).desc())
        .first()
    )
    top_category: str | None = top_cat_row[0] if top_cat_row else None

    # Savings estimate from user profile (lazy-load)
    savings_estimate: float | None = None
    try:
        from app.models.user import User  # noqa: PLC0415
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.monthly_income:
            savings_estimate = round(float(user.monthly_income) - round_avg, 2)
    except Exception:
        pass

    confidence = 0.7 if all(t > 0 for t in monthly_totals) else 0.3

    return {
        "next_month_spend": round_avg,
        "savings_estimate": savings_estimate,
        "top_category": top_category,
        "forecast": forecast,
        "trend": trend,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# detect_subscriptions
# ---------------------------------------------------------------------------

def detect_subscriptions(db: Session, user_id: str) -> list[dict]:
    """
    Detect recurring subscription-like expenses from the last 90 days.

    Logic:
      1. Look for expenses with a matching (merchant OR description) that appear
         in at least 2 different months within the last 90 days.
      2. Only flag them when the amounts are within 5% of each other.
      3. Cross-reference against already-tracked subscriptions to avoid duplicates.
      4. Return TrackedSubscription records that are already in the DB as well.

    Returns list of:
        {
            name          : str,
            amount        : float,
            billing_cycle : str,
            next_renewal  : str | None,   # ISO date
            detected      : str,          # "expense_pattern" | "tracked"
            source        : str,
        }
    """
    today = date.today()
    ninety_days_ago = today - timedelta(days=90)

    results: list[dict] = []

    # 1. Already-tracked subscriptions
    tracked = (
        db.query(TrackedSubscription)
        .filter(
            TrackedSubscription.user_id == user_id,
            TrackedSubscription.is_active == True,
        )
        .all()
    )
    tracked_names_lower = {t.name.lower() for t in tracked}

    for sub in tracked:
        results.append({
            "name": sub.name,
            "amount": float(sub.amount),
            "billing_cycle": sub.billing_cycle,
            "next_renewal": str(sub.next_renewal) if sub.next_renewal else None,
            "detected": "tracked",
            "source": "tracked_subscriptions",
        })

    # 2. Detect from expense patterns
    recent_expenses = (
        db.query(Expense)
        .filter(
            Expense.user_id == user_id,
            Expense.expense_date >= ninety_days_ago,
        )
        .order_by(Expense.expense_date.asc())
        .all()
    )

    # Group by normalised merchant / description key
    groups: dict[str, list[Expense]] = defaultdict(list)
    for exp in recent_expenses:
        key = (exp.merchant or exp.description or "").strip().lower()
        if key:
            groups[key].append(exp)

    for key, exps in groups.items():
        if len(exps) < 2:
            continue

        # Check if they span at least 2 distinct months
        months_seen = {(e.expense_date.year, e.expense_date.month) for e in exps}
        if len(months_seen) < 2:
            continue

        amounts = [float(e.amount) for e in exps]
        avg_amount = sum(amounts) / len(amounts)
        # All amounts within 5% of the average
        if not all(abs(a - avg_amount) / avg_amount < 0.05 for a in amounts):
            continue

        # Skip if already in tracked list
        if key in tracked_names_lower:
            continue

        # Infer billing cycle from gaps
        dates_sorted = sorted(e.expense_date for e in exps)
        gaps = [(dates_sorted[i + 1] - dates_sorted[i]).days for i in range(len(dates_sorted) - 1)]
        avg_gap = sum(gaps) / len(gaps) if gaps else 30
        if avg_gap <= 10:
            billing_cycle = "weekly"
            next_renewal = dates_sorted[-1] + timedelta(days=7)
        elif avg_gap <= 35:
            billing_cycle = "monthly"
            next_renewal = dates_sorted[-1] + timedelta(days=30)
        elif avg_gap <= 100:
            billing_cycle = "quarterly"
            next_renewal = dates_sorted[-1] + timedelta(days=90)
        else:
            billing_cycle = "yearly"
            next_renewal = dates_sorted[-1] + timedelta(days=365)

        display_name = (exps[-1].merchant or exps[-1].description or key).title()
        results.append({
            "name": display_name,
            "amount": round(avg_amount, 2),
            "billing_cycle": billing_cycle,
            "next_renewal": str(next_renewal),
            "detected": "expense_pattern",
            "source": "ai_detection",
        })

    return results
