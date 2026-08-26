from typing import List, Optional
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from app.models.budget import Budget
from app.models.expense import Expense
from app.core.exceptions import NotFoundError, ForbiddenError
from app.api.v1.budgets.schemas import CreateBudgetRequest, UpdateBudgetRequest


def _budget_to_dict(b: Budget, spent_override: Optional[float] = None,
                    amount_override: Optional[float] = None,
                    month: Optional[int] = None, year: Optional[int] = None) -> dict:
    amount = amount_override if amount_override is not None else float(b.amount)
    spent  = spent_override  if spent_override  is not None else float(b.spent)
    percent = round((spent / amount * 100), 2) if amount > 0 else 0
    now = __import__('datetime').datetime.utcnow()
    is_past = False
    if month and year:
        is_past = (year < now.year) or (year == now.year and month < now.month)
    return {
        "id": str(b.id),
        "user_id": str(b.user_id),
        "category_id": str(b.category_id) if b.category_id else None,
        "name": b.name,
        "amount": amount,
        "base_amount": float(b.amount),
        "spent": spent,
        "period": b.period,
        "start_date": str(b.start_date),
        "end_date": str(b.end_date) if b.end_date else None,
        "alert_threshold": float(b.alert_threshold),
        "is_active": b.is_active,
        "is_shared": b.is_shared,
        "family_group_id": str(b.family_group_id) if b.family_group_id else None,
        "percent_used": percent,
        "month": month,
        "year": year,
        "is_past_month": is_past,
    }


class BudgetService:
    def _resolve_root_category(self, db: Session, user_id: str, category_id: str) -> str:
        """Validate scope/ownership of a category and snap it to its main (root) category.

        Budgets are always set on a main category. If a sub-category or leaf is passed
        (e.g. from chat/AI or an older client), it is resolved up to its root so spend
        from every descendant rolls into the one main-category budget.
        """
        from app.models.category import Category
        from app.api.v1.categories.service import CategoryService
        cat = db.query(Category).filter(Category.id == category_id).first()
        if not cat:
            raise NotFoundError("Category not found")
        # Personal category must be owned by the user; family categories are scope-checked
        # by the budget's own is_shared/family_group_id flow, so allow them through here.
        if cat.family_group_id is None and str(cat.user_id) != str(user_id):
            raise ForbiddenError("Access denied to category")
        return CategoryService().get_root_id(db, category_id)

    def create(self, db: Session, user_id: str, data: CreateBudgetRequest) -> dict:
        family_group_id = None
        if data.is_shared:
            # Reuse the family service's group resolution (handles the
            # phone-format inconsistencies and admin-vs-joined-member
            # priority correctly) instead of a separate, easily-drifting
            # copy — and auto-creates a group if the user has none yet, so a
            # shared budget can never end up orphaned with no family_group_id.
            from app.api.v1.family.service import FamilyService
            group = FamilyService().get_or_create_user_group(db, user_id)
            family_group_id = str(group.id)

        # Budgets attach only to main categories — snap any sub/leaf up to its root
        category_id = data.category_id
        if category_id:
            category_id = self._resolve_root_category(db, user_id, category_id)

        budget = Budget(
            user_id=user_id,
            name=data.name,
            amount=data.amount,
            category_id=category_id,
            period=data.period,
            start_date=data.start_date,
            end_date=data.end_date,
            alert_threshold=data.alert_threshold,
            is_shared=data.is_shared,
            family_group_id=family_group_id,
        )
        db.add(budget)
        db.commit()
        db.refresh(budget)
        self.recalculate_spent(budget.id, db)
        db.refresh(budget)
        return _budget_to_dict(budget)

    def list(self, db: Session, user_id: str,
             month: Optional[int] = None, year: Optional[int] = None,
             shared: bool = False) -> List[dict]:
        from app.models.budget_month_amount import BudgetMonthAmount
        q = db.query(Budget).filter(
            Budget.user_id == user_id,
            Budget.is_active == True,
        )
        if shared:
            # Family mode → only shared/family budgets
            q = q.filter(Budget.is_shared == True)  # noqa: E712
        else:
            # Personal mode → only personal budgets (not shared with family)
            q = q.filter(Budget.is_shared == False)  # noqa: E712
        budgets = q.order_by(Budget.start_date.desc()).all()

        if month is not None and year is not None:
            result = []
            for b in budgets:
                # Get month-specific amount override if exists
                override = db.query(BudgetMonthAmount).filter(
                    BudgetMonthAmount.budget_id == str(b.id),
                    BudgetMonthAmount.month == month,
                    BudgetMonthAmount.year == year,
                ).first()
                amt = float(override.amount) if override else None
                spent = self._spent_for_month(b, db, month, year)
                result.append(_budget_to_dict(b, spent, amt, month, year))
            return result
        return [_budget_to_dict(b) for b in budgets]

    def set_monthly_amount(self, db: Session, budget_id: str, user_id: str,
                           month: int, year: int, amount: float,
                           update_future: bool = True) -> dict:
        """Set a month-specific budget amount. Optionally propagates to future months."""
        from app.models.budget_month_amount import BudgetMonthAmount
        import datetime

        b = db.query(Budget).filter(Budget.id == budget_id).first()
        if not b:
            from app.core.exceptions import NotFoundError
            raise NotFoundError("Budget not found")
        if str(b.user_id) != str(user_id):
            from app.core.exceptions import ForbiddenError
            raise ForbiddenError("Access denied")

        # Upsert for the requested month
        existing = db.query(BudgetMonthAmount).filter(
            BudgetMonthAmount.budget_id == budget_id,
            BudgetMonthAmount.month == month,
            BudgetMonthAmount.year == year,
        ).first()
        if existing:
            existing.amount = amount
        else:
            db.add(BudgetMonthAmount(
                budget_id=budget_id, month=month, year=year, amount=amount
            ))

        # Propagate to future months (next 12 months) if requested
        if update_future:
            now = datetime.datetime.utcnow()
            for i in range(1, 13):
                future_month = month + i
                future_year  = year
                if future_month > 12:
                    future_month -= 12
                    future_year  += 1
                # Only update if this future month doesn't already have a custom override
                # AND is not in the past
                if future_year < now.year or (future_year == now.year and future_month < now.month):
                    continue
                fut = db.query(BudgetMonthAmount).filter(
                    BudgetMonthAmount.budget_id == budget_id,
                    BudgetMonthAmount.month == future_month,
                    BudgetMonthAmount.year == future_year,
                ).first()
                if fut:
                    fut.amount = amount
                else:
                    db.add(BudgetMonthAmount(
                        budget_id=budget_id,
                        month=future_month, year=future_year, amount=amount,
                    ))

        # Also update base budget amount for future reference
        b.amount = amount
        db.commit()
        return _budget_to_dict(b, None, amount, month, year)

    def _get_category_ids(self, db: Session, category_id: str) -> list:
        """Return the category plus all descendant IDs (handles 3-level hierarchy)."""
        from app.api.v1.categories.service import CategoryService
        return CategoryService().get_descendant_ids(db, category_id)

    def _spent_for_month(self, b: Budget, db: Session, month: int, year: int) -> float:
        """Calculate how much was spent against this budget in a specific month.

        Shared family budgets follow the FAMILY group's cycle and count ALL
        members' group-tagged expenses; personal budgets follow the owner's
        personal cycle and count only their own (non-family) expenses.
        """
        from sqlalchemy import or_
        from datetime import datetime as _dt
        from app.utils.period import (
            get_month_start_day, get_group_month_start_day,
            period_window, resolve_anchor,
        )
        is_family = bool(b.is_shared and b.family_group_id)
        if is_family:
            start_day = get_group_month_start_day(db, str(b.family_group_id))
        else:
            start_day = get_month_start_day(db, str(b.user_id))
        ay, am = resolve_anchor(year, month, start_day, _dt.utcnow().date())
        win_start, win_end = period_window(ay, am, start_day)
        query = db.query(func.sum(Expense.amount)).filter(
            Expense.expense_date >= win_start,
            Expense.expense_date <= win_end,
        )
        if is_family:
            # Whole household: every member's expenses tagged to this group.
            query = query.filter(Expense.family_group_id == str(b.family_group_id))
        else:
            query = query.filter(Expense.user_id == b.user_id)
        if b.category_id:
            # Include expenses from the category AND all its descendants
            cat_ids = self._get_category_ids(db, str(b.category_id))
            query = query.filter(Expense.category_id.in_(cat_ids))
        else:
            budget_name_lower = (b.name or '').lower()
            keywords = None
            for key, kw_list in self._BUDGET_KEYWORDS.items():
                if key in budget_name_lower or budget_name_lower in key:
                    keywords = kw_list
                    break
            if not keywords:
                return 0.0
            conditions = []
            for kw in keywords:
                conditions.append(Expense.ai_category.ilike(f'%{kw}%'))
                conditions.append(Expense.description.ilike(f'%{kw}%'))
            query = query.filter(or_(*conditions))
        return float(query.scalar() or 0)

    def get_by_id(self, db: Session, budget_id: str, user_id: str) -> dict:
        b = db.query(Budget).filter(Budget.id == budget_id).first()
        if not b:
            raise NotFoundError("Budget not found")
        if str(b.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        return _budget_to_dict(b)

    def update(self, db: Session, budget_id: str, user_id: str, data: UpdateBudgetRequest) -> dict:
        b = db.query(Budget).filter(Budget.id == budget_id).first()
        if not b:
            raise NotFoundError("Budget not found")
        if str(b.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        updated = data.model_dump(exclude_unset=True)
        # Budgets attach only to main categories — snap any sub/leaf up to its root
        if updated.get("category_id"):
            updated["category_id"] = self._resolve_root_category(
                db, user_id, updated["category_id"]
            )
        for field, value in updated.items():
            setattr(b, field, value)
        db.commit()
        db.refresh(b)
        self.recalculate_spent(b.id, db)
        db.refresh(b)
        return _budget_to_dict(b)

    def delete(self, db: Session, budget_id: str, user_id: str) -> bool:
        b = db.query(Budget).filter(Budget.id == budget_id).first()
        if not b:
            raise NotFoundError("Budget not found")
        if str(b.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        db.delete(b)
        db.commit()
        return True

    # Map budget names → expense ai_category / description keywords
    _BUDGET_KEYWORDS = {
        'house rent': ['Bills & Utilities', 'rent', 'house rent'],
        'groceries': ['Groceries', 'grocery'],
        'food & dining': ['Food & Dining', 'food', 'dining'],
        'transport': ['Transport', 'transport', 'fuel', 'petrol'],
        'bills': ['Bills & Utilities', 'bill', 'electricity', 'utility'],
        'shopping': ['Shopping', 'shopping', 'clothes'],
        'education': ['Education', 'school', 'education', 'fees'],
        'health': ['Health', 'medical', 'medicine', 'hospital'],
        'entertainment': ['Entertainment', 'netflix', 'movie'],
        'investments': ['General', 'investment'],
        'personal care': ['Personal Care', 'salon', 'grooming'],
    }

    def recalculate_spent(self, budget_id: str, db: Session) -> float:
        from sqlalchemy import or_
        b = db.query(Budget).filter(Budget.id == budget_id).first()
        if not b:
            return 0.0

        query = db.query(func.sum(Expense.amount)).filter(
            Expense.user_id == b.user_id,
            Expense.expense_date >= b.start_date,
        )
        if b.end_date:
            query = query.filter(Expense.expense_date <= b.end_date)

        if b.category_id:
            # Include expenses from the category AND all its descendants
            cat_ids = self._get_category_ids(db, str(b.category_id))
            query = query.filter(Expense.category_id.in_(cat_ids))
        else:
            # No category linked — match by budget name keywords
            budget_name_lower = (b.name or '').lower()
            keywords = None
            for key, kw_list in self._BUDGET_KEYWORDS.items():
                if key in budget_name_lower or budget_name_lower in key:
                    keywords = kw_list
                    break

            if not keywords:
                # No keyword match — skip to avoid summing all expenses
                return float(b.spent)

            # Match ai_category OR description contains keyword
            conditions = []
            for kw in keywords:
                conditions.append(Expense.ai_category.ilike(f'%{kw}%'))
                conditions.append(Expense.description.ilike(f'%{kw}%'))
            query = query.filter(or_(*conditions))

        total = query.scalar() or 0
        b.spent = total
        db.commit()
        return float(total)

    def get_summary(self, db: Session, user_id: str) -> dict:
        budgets = db.query(Budget).filter(Budget.user_id == user_id, Budget.is_active == True).all()
        total_budget = sum(float(b.amount) for b in budgets)
        total_spent = sum(float(b.spent) for b in budgets)
        over_budget = [b for b in budgets if float(b.spent) > float(b.amount)]
        near_limit = [b for b in budgets if float(b.amount) > 0 and (float(b.spent) / float(b.amount) * 100) >= float(b.alert_threshold) and float(b.spent) <= float(b.amount)]
        return {
            "total_budget": total_budget,
            "total_spent": total_spent,
            "remaining": max(0.0, total_budget - total_spent),
            "percent_used": round((total_spent / total_budget * 100), 2) if total_budget > 0 else 0,
            "active_budgets": len(budgets),
            "over_budget_count": len(over_budget),
            "near_limit_count": len(near_limit),
        }

    def recalculate_all_for_user(self, db: Session, user_id: str) -> int:
        budgets = db.query(Budget).filter(Budget.user_id == user_id, Budget.is_active == True).all()
        for b in budgets:
            self.recalculate_spent(str(b.id), db)
        return len(budgets)

    def get_alerts(self, db: Session, user_id: str) -> List[dict]:
        budgets = db.query(Budget).filter(Budget.user_id == user_id, Budget.is_active == True).all()
        alerts = []
        for b in budgets:
            amount = float(b.amount)
            spent = float(b.spent)
            if amount > 0:
                percent = (spent / amount) * 100
                if percent >= float(b.alert_threshold):
                    alerts.append({
                        "budget_id": str(b.id),
                        "name": b.name,
                        "amount": amount,
                        "spent": spent,
                        "percent_used": round(percent, 2),
                        "threshold": float(b.alert_threshold),
                        "status": "exceeded" if percent >= 100 else "warning",
                    })
        return alerts
