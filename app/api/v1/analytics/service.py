from sqlalchemy.orm import Session
from sqlalchemy import extract, func, text
from datetime import datetime, date, timedelta
from calendar import monthrange

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# Financial-cycle helpers live in app/utils/period.py (shared across the app).
from app.utils.period import (  # noqa: E402
    get_month_start_day,
    get_group_month_start_day,
    period_window,
    resolve_anchor,
    prev_month as _prev_month,
    next_month as _next_month,
)


class AnalyticsService:

    def _scope(self, db: Session, user_id: str, shared: bool, alias: str = ""):
        """Resolve the expense scope for analytics queries.

        Returns (where_fragment, params, group):
          - shared=True (and in a group) → family-pooled expenses
          - otherwise                    → the user's personal expenses
        `alias` is an optional table prefix like 'e.' for joined queries.
        """
        group = None
        if shared:
            from app.api.v1.family.service import FamilyService
            group = FamilyService()._get_user_group(db, user_id)
        fg = f"{alias}family_group_id"
        ui = f"{alias}user_id"
        if group:
            return f"{fg} = :gid", {"gid": str(group.id)}, group
        return f"{ui} = :uid AND {fg} IS NULL", {"uid": user_id}, group

    def _cycle_start_day(self, db: Session, user_id: str, group) -> int:
        """Cycle start day for the current scope.

        Family scope follows the group's shared cycle; personal scope follows
        the user's own ``month_start_day``. (Previously family analytics wrongly
        inherited the *calling* user's personal cycle.)
        """
        if group is not None:
            return get_group_month_start_day(db, group.id)
        return get_month_start_day(db, user_id)

    def get_monthly(self, user_id: str, month: str, db: Session,
                    shared: bool = False) -> dict:
        """month format: YYYY-MM"""
        try:
            year, mo = int(month[:4]), int(month[5:7])
        except Exception:
            now = datetime.utcnow()
            year, mo = now.year, now.month

        scope_sql, scope_params, group = self._scope(db, user_id, shared)

        start_day = self._cycle_start_day(db, user_id, group)
        ay, am = resolve_anchor(year, mo, start_day, datetime.utcnow().date())
        month_start, month_end = period_window(ay, am, start_day)
        days_in_period = (month_end - month_start).days + 1

        # Previous cycle window
        py, pm = _prev_month(ay, am)
        prev_month_start, prev_month_end = period_window(py, pm, start_day)

        # Daily spending across the cycle
        daily = db.execute(text(f"""
            SELECT expense_date::date as day, COALESCE(SUM(amount), 0) as total
            FROM expenses
            WHERE {scope_sql}
              AND expense_date >= :start AND expense_date <= :end
            GROUP BY expense_date::date
            ORDER BY day
        """), {**scope_params, "start": month_start, "end": month_end}).fetchall()

        # Fill missing days with 0 across the actual window
        daily_map = {str(r.day): float(r.total) for r in daily}
        daily_data = []
        for i in range(days_in_period):
            d = month_start + timedelta(days=i)
            day_str = d.isoformat()
            daily_data.append({"date": day_str, "amount": daily_map.get(day_str, 0.0)})

        total = sum(p["amount"] for p in daily_data)

        # Previous cycle total
        prev_total = db.execute(text(f"""
            SELECT COALESCE(SUM(amount), 0) as total FROM expenses
            WHERE {scope_sql}
              AND expense_date >= :start AND expense_date <= :end
        """), {**scope_params, "start": prev_month_start, "end": prev_month_end}).scalar() or 0

        change_pct = 0.0
        if float(prev_total) > 0:
            change_pct = round(((total - float(prev_total)) / float(prev_total)) * 100, 1)

        return {
            "month": month,
            "daily_data": daily_data,
            "total": round(total, 2),
            "avg_daily": round(total / days_in_period, 2) if days_in_period else 0.0,
            "prev_month_total": round(float(prev_total), 2),
            "change_pct": change_pct,
            "period_start": month_start.isoformat(),
            "period_end": month_end.isoformat(),
            "month_start_day": start_day,
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

        start_day = get_month_start_day(db, user_id)
        ay, am = resolve_anchor(year, month, start_day, datetime.utcnow().date())
        month_start, month_end = period_window(ay, am, start_day)

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

    def get_category_breakdown(self, user_id: str, month: int, year: int,
                               db: Session, shared: bool = False) -> dict:
        """
        Monthly spend grouped as top-level category → the specific item it was
        tagged to.

        Every expense links to the DEEPEST category node it was filed under
        (e.g. "Milk" under Groceries → Dairy Product, or "Water" under Bills &
        Utilities). We group each expense under its ROOT category, and within
        that show the actual tagged node as the sub-row — so the user can see
        exactly how much went to milk, vegetables, water, etc. in a month.
        """
        from app.models.category import Category

        scope_sql, scope_params, group = self._scope(db, user_id, shared)

        start_day = self._cycle_start_day(db, user_id, group)
        ay, am = resolve_anchor(year, month, start_day, datetime.utcnow().date())
        month_start, month_end = period_window(ay, am, start_day)

        # 1) Spend grouped by the (deepest) category node the expense links to.
        rows = db.execute(text(f"""
            SELECT category_id, SUM(amount) AS amount, COUNT(*) AS cnt
            FROM expenses
            WHERE {scope_sql}
              AND expense_date >= :start AND expense_date <= :end
            GROUP BY category_id
        """), {**scope_params, "start": month_start, "end": month_end}).fetchall()

        # 2) Load every category in scope into a lookup so we can walk parents.
        cat_q = db.query(Category)
        if group is not None:
            cat_q = cat_q.filter(Category.family_group_id == str(group.id))
        else:
            cat_q = cat_q.filter(
                Category.user_id == user_id, Category.family_group_id.is_(None))
        cat_rows = cat_q.all()
        cat_map = {str(c.id): c for c in cat_rows}

        def _root_and_node(node_id):
            """Return (root, node): the level-0 ancestor (top category) and the
            tagged node itself. `node` is None if the id is unknown."""
            node = cat_map.get(node_id)
            if node is None:
                return None, None
            root, cur, seen = node, node, set()
            while cur is not None and str(cur.id) not in seen:
                root = cur
                seen.add(str(cur.id))
                cur = cat_map.get(str(cur.parent_id)) if cur.parent_id else None
            return root, node

        # 3) Accumulate into category → sub-category buckets.
        cats: dict = {}
        UNCATEGORIZED = "Uncategorized"
        for r in rows:
            amount = float(r.amount or 0)
            cnt = int(r.cnt or 0)
            root, node = (None, None) if r.category_id is None else _root_and_node(str(r.category_id))

            if root is None:
                key, name, color, icon = UNCATEGORIZED, UNCATEGORIZED, "#6B7280", None
            else:
                key, name, color, icon = str(root.id), root.name, (root.color or "#6B7280"), root.icon

            bucket = cats.setdefault(key, {
                "category": name, "color": color, "icon": icon,
                "amount": 0.0, "transaction_count": 0, "_subs": {},
            })
            bucket["amount"] += amount
            bucket["transaction_count"] += cnt

            # Sub-row = the specific node the expense was tagged to (e.g. "Milk",
            # "Vegetables", "Water"). "General" when booked straight on the top
            # category with nothing more specific.
            sub_name = node.name if (node is not None and node is not root) else "General"
            sub_bucket = bucket["_subs"].setdefault(sub_name, {
                "name": sub_name, "amount": 0.0, "transaction_count": 0,
            })
            sub_bucket["amount"] += amount
            sub_bucket["transaction_count"] += cnt

        grand_total = sum(b["amount"] for b in cats.values())

        categories = []
        for b in cats.values():
            subs = sorted(b["_subs"].values(), key=lambda s: s["amount"], reverse=True)
            cat_total = b["amount"]
            categories.append({
                "category": b["category"],
                "color": b["color"],
                "icon": b["icon"],
                "amount": round(cat_total, 2),
                "transaction_count": b["transaction_count"],
                "percent": round((cat_total / grand_total * 100), 1) if grand_total > 0 else 0.0,
                "subcategories": [
                    {
                        "name": s["name"],
                        "amount": round(s["amount"], 2),
                        "transaction_count": s["transaction_count"],
                        # percent within the parent category
                        "percent": round((s["amount"] / cat_total * 100), 1) if cat_total > 0 else 0.0,
                    }
                    for s in subs
                ],
            })

        categories.sort(key=lambda c: c["amount"], reverse=True)
        return {
            "month": month,
            "year": year,
            "total": round(grand_total, 2),
            "categories": categories,
            "period_start": month_start.isoformat(),
            "period_end": month_end.isoformat(),
            "month_start_day": start_day,
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

        # Anchor on the cycle that contains today, then step back month by month.
        start_day = get_month_start_day(db, user_id)
        cur_y, cur_m = resolve_anchor(now.year, now.month, start_day, now.date())

        for i in range(months - 1, -1, -1):
            yr, mo = cur_y, cur_m
            for _ in range(i):
                yr, mo = _prev_month(yr, mo)
            month_start, month_end = period_window(yr, mo, start_day)

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
