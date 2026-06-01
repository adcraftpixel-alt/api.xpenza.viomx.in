from typing import List, Optional
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from app.models.budget import Budget
from app.models.expense import Expense
from app.core.exceptions import NotFoundError, ForbiddenError
from app.api.v1.budgets.schemas import CreateBudgetRequest, UpdateBudgetRequest


def _budget_to_dict(b: Budget, spent_override: Optional[float] = None) -> dict:
    amount = float(b.amount)
    spent = spent_override if spent_override is not None else float(b.spent)
    percent = round((spent / amount * 100), 2) if amount > 0 else 0
    return {
        "id": str(b.id),
        "user_id": str(b.user_id),
        "category_id": str(b.category_id) if b.category_id else None,
        "name": b.name,
        "amount": amount,
        "spent": spent,
        "period": b.period,
        "start_date": str(b.start_date),
        "end_date": str(b.end_date) if b.end_date else None,
        "alert_threshold": float(b.alert_threshold),
        "is_active": b.is_active,
        "is_shared": b.is_shared,
        "family_group_id": str(b.family_group_id) if b.family_group_id else None,
        "percent_used": percent,
    }


class BudgetService:
    def create(self, db: Session, user_id: str, data: CreateBudgetRequest) -> dict:
        family_group_id = None
        if data.is_shared:
            from app.models.family_group import FamilyGroup, FamilyGroupMember
            from app.models.user import User
            group = db.query(FamilyGroup).filter(FamilyGroup.created_by == user_id).first()
            if not group:
                user = db.query(User).filter(User.id == user_id).first()
                if user and user.phone:
                    member = db.query(FamilyGroupMember).filter(
                        FamilyGroupMember.phone == user.phone,
                        FamilyGroupMember.status == "accepted",
                    ).first()
                    if member:
                        group = db.query(FamilyGroup).filter(FamilyGroup.id == member.group_id).first()
            if group:
                family_group_id = str(group.id)

        budget = Budget(
            user_id=user_id,
            name=data.name,
            amount=data.amount,
            category_id=data.category_id,
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
             month: Optional[int] = None, year: Optional[int] = None) -> List[dict]:
        budgets = db.query(Budget).filter(
            Budget.user_id == user_id
        ).order_by(Budget.start_date.desc()).all()

        if month is not None and year is not None:
            # Calculate spent only for the requested month
            return [_budget_to_dict(b, self._spent_for_month(b, db, month, year)) for b in budgets]
        return [_budget_to_dict(b) for b in budgets]

    def _spent_for_month(self, b: Budget, db: Session, month: int, year: int) -> float:
        """Calculate how much was spent against this budget in a specific month."""
        from sqlalchemy import or_
        query = db.query(func.sum(Expense.amount)).filter(
            Expense.user_id == b.user_id,
            extract('year', Expense.expense_date) == year,
            extract('month', Expense.expense_date) == month,
        )
        if b.category_id:
            query = query.filter(Expense.category_id == b.category_id)
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
        for field, value in data.model_dump(exclude_unset=True).items():
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
            # Linked to a category — exact match
            query = query.filter(Expense.category_id == b.category_id)
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
