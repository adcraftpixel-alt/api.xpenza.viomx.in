from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.expense import Expense
from app.models.budget import Budget
from app.models.savings_goal import SavingsGoal
from app.models.category import Category


class DashboardService:
    def get_summary(self, db: Session, user_id: str, user) -> dict:
        today = date.today()
        this_month_start = today.replace(day=1)
        if today.month == 1:
            last_month_start = today.replace(year=today.year - 1, month=12, day=1)
            last_month_end = this_month_start
        else:
            last_month_start = today.replace(month=today.month - 1, day=1)
            last_month_end = this_month_start

        this_month = float(
            db.query(func.sum(Expense.amount))
            .filter(Expense.user_id == user_id, Expense.expense_date >= this_month_start)
            .scalar() or 0
        )
        last_month = float(
            db.query(func.sum(Expense.amount))
            .filter(
                Expense.user_id == user_id,
                Expense.expense_date >= last_month_start,
                Expense.expense_date < last_month_end,
            )
            .scalar() or 0
        )
        change_pct = 0.0
        if last_month > 0:
            change_pct = round(((this_month - last_month) / last_month) * 100, 2)

        monthly_income = float(user.monthly_income) if user.monthly_income else None
        savings_rate = None
        if monthly_income and monthly_income > 0:
            savings_rate = round(((monthly_income - this_month) / monthly_income) * 100, 2)

        # Budgets
        active_budgets = db.query(Budget).filter(Budget.user_id == user_id, Budget.is_active == True).count()
        budget_alerts_count = 0
        budgets = db.query(Budget).filter(Budget.user_id == user_id, Budget.is_active == True).all()
        budget_overview = []
        for b in budgets:
            amt = float(b.amount)
            spent = float(b.spent)
            pct = round((spent / amt * 100), 2) if amt > 0 else 0
            if pct >= float(b.alert_threshold):
                budget_alerts_count += 1
            budget_overview.append({
                "id": str(b.id),
                "name": b.name,
                "amount": amt,
                "spent": spent,
                "percent_used": pct,
            })

        # Savings goals
        goals = db.query(SavingsGoal).filter(SavingsGoal.user_id == user_id).all()
        goals_on_track = sum(
            1 for g in goals
            if not g.is_completed and float(g.current_amount) > 0
        )

        # Top categories this month
        cat_rows = (
            db.query(Category.name, func.sum(Expense.amount).label("total"))
            .join(Expense, Expense.category_id == Category.id, isouter=True)
            .filter(Expense.user_id == user_id, Expense.expense_date >= this_month_start)
            .group_by(Category.name)
            .order_by(func.sum(Expense.amount).desc())
            .limit(5)
            .all()
        )
        top_categories = [{"category": r.name, "total": float(r.total)} for r in cat_rows]

        # Recent expenses
        recent = (
            db.query(Expense)
            .filter(Expense.user_id == user_id)
            .order_by(Expense.expense_date.desc())
            .limit(5)
            .all()
        )
        recent_list = [
            {
                "id": str(e.id),
                "amount": float(e.amount),
                "merchant": e.merchant,
                "description": e.description,
                "expense_date": str(e.expense_date),
                "category_id": str(e.category_id) if e.category_id else None,
            }
            for e in recent
        ]

        return {
            "total_this_month": this_month,
            "total_last_month": last_month,
            "change_percent": change_pct,
            "monthly_income": monthly_income,
            "savings_rate": savings_rate,
            "active_budgets": active_budgets,
            "budget_alerts": budget_alerts_count,
            "savings_goals": len(goals),
            "goals_on_track": goals_on_track,
            "recent_expenses": recent_list,
            "top_categories": top_categories,
            "budget_overview": budget_overview,
        }
