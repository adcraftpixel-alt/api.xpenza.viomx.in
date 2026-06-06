from sqlalchemy.orm import Session
from sqlalchemy import extract, func, text
from datetime import datetime, date, timedelta
from calendar import monthrange

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class AnalyticsService:

    def get_monthly(self, user_id: str, month: str, db: Session) -> dict:
        """month format: YYYY-MM"""
        try:
            year, mo = int(month[:4]), int(month[5:7])
        except Exception:
            now = datetime.utcnow()
            year, mo = now.year, now.month

        month_start = date(year, mo, 1)
        _, days_in_month = monthrange(year, mo)
        month_end = date(year, mo, days_in_month)

        prev_month_end = month_start - timedelta(days=1)
        prev_month_start = date(prev_month_end.year, prev_month_end.month, 1)

        # Daily spending for the month
        daily = db.execute(text("""
            SELECT expense_date::date as day, COALESCE(SUM(amount), 0) as total
            FROM expenses
            WHERE user_id = :uid AND family_group_id IS NULL
              AND expense_date >= :start AND expense_date <= :end
            GROUP BY expense_date::date
            ORDER BY day
        """), {"uid": user_id, "start": month_start, "end": month_end}).fetchall()

        # Fill missing days with 0
        daily_map = {str(r.day): float(r.total) for r in daily}
        daily_data = []
        for d in range(1, days_in_month + 1):
            day_str = f"{year}-{mo:02d}-{d:02d}"
            daily_data.append({"date": day_str, "amount": daily_map.get(day_str, 0.0)})

        total = sum(p["amount"] for p in daily_data)

        # Previous month total
        prev_total = db.execute(text("""
            SELECT COALESCE(SUM(amount), 0) as total FROM expenses
            WHERE user_id = :uid AND family_group_id IS NULL
              AND expense_date >= :start AND expense_date <= :end
        """), {"uid": user_id, "start": prev_month_start, "end": prev_month_end}).scalar() or 0

        change_pct = 0.0
        if float(prev_total) > 0:
            change_pct = round(((total - float(prev_total)) / float(prev_total)) * 100, 1)

        return {
            "month": month,
            "daily_data": daily_data,
            "total": round(total, 2),
            "avg_daily": round(total / days_in_month, 2),
            "prev_month_total": round(float(prev_total), 2),
            "change_pct": change_pct,
        }

    def get_categories(self, user_id: str, start_date: str, end_date: str, db: Session) -> dict:
        rows = db.execute(text("""
            SELECT
                COALESCE(c.name, 'Uncategorized') as category,
                COALESCE(c.color, '#6B7280') as color,
                SUM(e.amount) as total
            FROM expenses e
            LEFT JOIN categories c ON c.id = e.category_id
            WHERE e.user_id = :uid AND e.family_group_id IS NULL
              AND e.expense_date >= :start AND e.expense_date <= :end
            GROUP BY c.name, c.color
            ORDER BY total DESC
        """), {"uid": user_id, "start": start_date, "end": end_date}).fetchall()

        grand_total = sum(float(r.total) for r in rows)
        categories = [
            {
                "category": r.category,
                "amount": round(float(r.total), 2),
                "percentage": round((float(r.total) / grand_total * 100), 1) if grand_total > 0 else 0,
                "color": r.color,
            }
            for r in rows
        ]
        return {"period": f"{start_date} to {end_date}", "categories": categories, "total": round(grand_total, 2)}

    def get_income_vs_expense(self, user_id: str, months: int, db: Session) -> list:
        result = []
        now = datetime.utcnow()

        # Get user income
        income = db.execute(text(
            "SELECT COALESCE(monthly_income, 0) FROM users WHERE id = :uid"
        ), {"uid": user_id}).scalar() or 0

        for i in range(months - 1, -1, -1):
            target = now.replace(day=1) - timedelta(days=i * 28)
            year, mo = target.year, target.month
            _, days = monthrange(year, mo)
            month_start = date(year, mo, 1)
            month_end = date(year, mo, days)

            expense_total = db.execute(text("""
                SELECT COALESCE(SUM(amount), 0) FROM expenses
                WHERE user_id = :uid AND expense_date >= :start AND expense_date <= :end
            """), {"uid": user_id, "start": month_start, "end": month_end}).scalar() or 0

            expense_total = float(expense_total)
            income_val = float(income)
            result.append({
                "month": f"{year}-{mo:02d}",
                "income": income_val,
                "expenses": round(expense_total, 2),
                "savings": round(max(income_val - expense_total, 0), 2),
            })

        return result

    def get_yearly(self, user_id: str, year: int, db: Session) -> dict:
        monthly = db.execute(text("""
            SELECT
                EXTRACT(MONTH FROM expense_date)::int as month,
                SUM(amount) as total
            FROM expenses
            WHERE user_id = :uid AND EXTRACT(YEAR FROM expense_date) = :year
            GROUP BY month ORDER BY month
        """), {"uid": user_id, "year": year}).fetchall()

        monthly_map = {r.month: float(r.total) for r in monthly}
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        monthly_data = [{"month": month_names[i], "amount": monthly_map.get(i + 1, 0.0)} for i in range(12)]
        total = sum(p["amount"] for p in monthly_data)

        return {
            "year": year,
            "monthly_data": monthly_data,
            "total": round(total, 2),
            "avg_monthly": round(total / 12, 2),
        }

    def get_payment_methods(self, user_id: str, month: str, db: Session) -> list:
        try:
            year, mo = int(month[:4]), int(month[5:7])
        except Exception:
            now = datetime.utcnow()
            year, mo = now.year, now.month
        _, days = monthrange(year, mo)

        rows = db.execute(text("""
            SELECT
                COALESCE(payment_method, 'Other') as method,
                SUM(amount) as total,
                COUNT(*) as count
            FROM expenses
            WHERE user_id = :uid
              AND expense_date >= :start AND expense_date <= :end
            GROUP BY payment_method ORDER BY total DESC
        """), {"uid": user_id,
               "start": date(year, mo, 1),
               "end": date(year, mo, days)}).fetchall()

        grand_total = sum(float(r.total) for r in rows)
        return [
            {
                "method": r.method,
                "amount": round(float(r.total), 2),
                "count": r.count,
                "percentage": round(float(r.total) / grand_total * 100, 1) if grand_total > 0 else 0
            }
            for r in rows
        ]


    def get_categories_by_month(self, user_id: str, month: int, year: int, db: Session) -> dict:
        """Group expenses by ai_category for a specific month/year."""
        from app.models.expense import Expense

        month_start = date(year, month, 1)
        _, days_in_month = monthrange(year, month)
        month_end = date(year, month, days_in_month)

        rows = (
            db.query(
                func.coalesce(Expense.ai_category, "Uncategorized").label("category"),
                func.sum(Expense.amount).label("amount"),
                func.count(Expense.id).label("transaction_count"),
            )
            .filter(
                Expense.user_id == user_id,
                Expense.family_group_id.is_(None),
                Expense.expense_date >= month_start,
                Expense.expense_date <= month_end,
            )
            .group_by(func.coalesce(Expense.ai_category, "Uncategorized"))
            .order_by(func.sum(Expense.amount).desc())
            .all()
        )

        grand_total = sum(float(r.amount) for r in rows)
        categories = [
            {
                "category": r.category,
                "amount": round(float(r.amount), 2),
                "percent": round((float(r.amount) / grand_total * 100), 1) if grand_total > 0 else 0.0,
                "transaction_count": r.transaction_count,
            }
            for r in rows
        ]
        return {
            "categories": categories,
            "total": round(grand_total, 2),
            "month": month,
            "year": year,
        }

    def get_income_vs_expense_summary(self, user_id: str, months: int, db: Session) -> dict:
        """Return last N months of income vs expense with totals."""
        from app.models.expense import Expense
        from app.models.user import User as UserModel

        now = datetime.utcnow()

        monthly_income = (
            db.query(UserModel.monthly_income)
            .filter(UserModel.id == user_id)
            .scalar()
        ) or 0.0
        monthly_income = float(monthly_income)

        result_months = []
        total_income = 0.0
        total_expense = 0.0

        for i in range(months - 1, -1, -1):
            # Step back by i months from the current month
            target = now.replace(day=1) - timedelta(days=i * 28)
            yr, mo = target.year, target.month
            _, days = monthrange(yr, mo)
            month_start = date(yr, mo, 1)
            month_end = date(yr, mo, days)

            expense_total = (
                db.query(func.coalesce(func.sum(Expense.amount), 0))
                .filter(
                    Expense.user_id == user_id,
                    Expense.expense_date >= month_start,
                    Expense.expense_date <= month_end,
                )
                .scalar()
            ) or 0.0
            expense_total = round(float(expense_total), 2)

            saved = round(max(monthly_income - expense_total, 0.0), 2)
            total_income += monthly_income
            total_expense += expense_total

            result_months.append({
                "month_name": MONTH_NAMES[mo - 1],
                "year": yr,
                "income": round(monthly_income, 2),
                "expense": expense_total,
                "saved": saved,
            })

        return {
            "months": result_months,
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "total_saved": round(max(total_income - total_expense, 0.0), 2),
        }


analytics_service = AnalyticsService()
