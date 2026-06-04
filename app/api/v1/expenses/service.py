import math
import logging
from datetime import date, datetime
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from app.models.expense import Expense
from app.models.category import Category
from app.core.exceptions import NotFoundError, ForbiddenError
from app.api.v1.expenses.schemas import CreateExpenseRequest, UpdateExpenseRequest

logger = logging.getLogger(__name__)


def _expense_to_dict(e: Expense) -> dict:
    cat = e.category  # relationship — already loaded via selectin/joined load
    return {
        "id": str(e.id),
        "user_id": str(e.user_id),
        "category_id": str(e.category_id) if e.category_id else None,
        "category_name":  cat.name  if cat else (e.ai_category or "General"),
        "category_icon":  cat.icon  if cat else "💰",
        "category_color": cat.color if cat else "#6B7280",
        "amount": float(e.amount),
        "currency": e.currency,
        "description": e.description,
        "merchant": e.merchant,
        "payment_method": e.payment_method,
        "expense_date": str(e.expense_date),
        "is_recurring": e.is_recurring,
        "recurring_interval": e.recurring_interval,
        "receipt_url": e.receipt_url,
        "tags": e.tags,
        "source": e.source,
        "ai_category": e.ai_category,
        "notes": e.notes,
        "created_at": str(e.created_at),
    }


class ExpenseService:
    # Keyword-based auto-categorization (runs server-side as fallback)
    _CATEGORY_RULES = [
        ('House Rent / EMI',     r'rent|house rent|emi|home loan|mortgage|pg|room rent|flat|maintenance|society'),
        ('Food & Dining',        r'food|dinner|lunch|breakfast|coffee|restaurant|zomato|swiggy|cafe|pizza|burger|tea|chai|biryani|dosa|hotel|dhaba|meal|thali|snack'),
        ('Groceries',            r'grocery|groceries|vegetable|sabzi|fruit|milk|supermarket|blinkit|zepto|instamart|bigbasket|dmart|atta|rice|dal|oil|ghee|paneer|curd|bread|egg'),
        ('Transport / Fuel',     r'uber|ola|auto|cab|metro|bus|petrol|diesel|fuel|train|taxi|bike|ride|rapido|toll|parking|flight|airline|irctc'),
        ('Shopping',             r'cloth|clothes|shirt|pant|jeans|dress|kurta|saree|shoes|footwear|sandal|jacket|sweater|myntra|meesho|amazon|flipkart|shopping|fashion|outfit'),
        ('Bills & Subscriptions',r'electricity|electric|bijli|wifi|internet|broadband|mobile|recharge|sim|gas|cylinder|lpg|water bill|bill|utility|dth|cable|jio|airtel|bsnl|netflix|spotify|prime|hotstar|subscription'),
        ('Entertainment',        r'movie|cinema|pvr|inox|gaming|concert|event|bookmyshow|steam|youtube|ott'),
        ('Health & Medical',     r'doctor|medicine|hospital|pharmacy|medical|clinic|lab|tablet|capsule|syrup|apollo|medplus|gym|fitness|yoga|protein|supplement|test|scan|xray'),
        ('Education',            r'school|college|fees|fee|tuition|course|coaching|book|notebook|stationery|udemy|coursera|class|exam|education'),
        ('Travel',               r'hotel|resort|trip|travel|vacation|holiday|tour|oyo|booking|makemytrip|goibibo|airbnb'),
        ('Personal Care',        r'salon|haircut|barber|parlour|spa|massage|skin|cream|lotion|cosmetic|makeup|perfume'),
        ('Investments',          r'invest|sip|mutual fund|stocks|shares|fd|fixed deposit|ppf|nps|insurance|premium|policy'),
    ]

    def _auto_categorize(self, description: str, ai_category: str | None) -> str:
        import re
        if ai_category:
            return ai_category
        desc = (description or '').lower()
        for category, pattern in self._CATEGORY_RULES:
            if re.search(pattern, desc):
                return category
        return 'General'

    def create(self, db: Session, user_id: str, data: CreateExpenseRequest) -> dict:
        ai_cat = self._auto_categorize(data.description or '', getattr(data, 'ai_category', None))
        expense = Expense(
            user_id=user_id,
            category_id=data.category_id,
            amount=data.amount,
            currency=data.currency,
            description=data.description,
            merchant=data.merchant,
            payment_method=data.payment_method,
            expense_date=data.expense_date,
            is_recurring=data.is_recurring,
            recurring_interval=data.recurring_interval,
            tags=data.tags,
            source=data.source,
            notes=data.notes,
            ai_category=ai_cat,
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        self._trigger_budget_recalc(db, user_id)
        return _expense_to_dict(expense)

    def get_by_id(self, db: Session, expense_id: str, user_id: str) -> dict:
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if not expense:
            raise NotFoundError("Expense not found")
        if str(expense.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        return _expense_to_dict(expense)

    def list(
        self,
        db: Session,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
        category_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        payment_method: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
    ) -> dict:
        query = db.query(Expense).filter(Expense.user_id == user_id)
        if category_id:
            query = query.filter(Expense.category_id == category_id)
        if start_date:
            query = query.filter(Expense.expense_date >= start_date)
        if end_date:
            query = query.filter(Expense.expense_date <= end_date)
        if payment_method:
            query = query.filter(Expense.payment_method == payment_method)
        if min_amount is not None:
            query = query.filter(Expense.amount >= min_amount)
        if max_amount is not None:
            query = query.filter(Expense.amount <= max_amount)

        total = query.count()
        expenses = query.order_by(Expense.expense_date.desc()).offset((page - 1) * page_size).limit(page_size).all()

        return {
            "items": [_expense_to_dict(e) for e in expenses],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total > 0 else 0,
        }

    def update(self, db: Session, expense_id: str, user_id: str, data: UpdateExpenseRequest) -> dict:
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if not expense:
            raise NotFoundError("Expense not found")
        if str(expense.user_id) != str(user_id):
            raise ForbiddenError("Access denied")

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(expense, field, value)
        db.commit()
        db.refresh(expense)
        self._trigger_budget_recalc(db, user_id)
        return _expense_to_dict(expense)

    def delete(self, db: Session, expense_id: str, user_id: str) -> bool:
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if not expense:
            raise NotFoundError("Expense not found")
        if str(expense.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        db.delete(expense)
        db.commit()
        self._trigger_budget_recalc(db, user_id)
        return True

    def _trigger_budget_recalc(self, db: Session, user_id: str) -> None:
        from app.api.v1.budgets.service import BudgetService
        try:
            BudgetService().recalculate_all_for_user(db, user_id)
        except Exception:
            pass

    def search(self, db: Session, user_id: str, q: str, page: int = 1, page_size: int = 20) -> dict:
        from sqlalchemy import or_
        query = db.query(Expense).filter(
            Expense.user_id == user_id,
            or_(
                Expense.description.ilike(f"%{q}%"),
                Expense.merchant.ilike(f"%{q}%"),
                Expense.notes.ilike(f"%{q}%"),
            ),
        )
        total = query.count()
        items = query.order_by(Expense.expense_date.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {
            "items": [_expense_to_dict(e) for e in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total > 0 else 0,
        }

    def get_recurring(self, db: Session, user_id: str) -> List[dict]:
        expenses = db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.is_recurring == True,
        ).all()
        return [_expense_to_dict(e) for e in expenses]

    def get_summary(self, db: Session, user_id: str) -> dict:
        today = date.today()
        this_month_start = today.replace(day=1)
        if today.month == 1:
            last_month_start = today.replace(year=today.year - 1, month=12, day=1)
            last_month_end = today.replace(day=1)
        else:
            last_month_start = today.replace(month=today.month - 1, day=1)
            last_month_end = this_month_start

        this_month = db.query(func.sum(Expense.amount)).filter(
            Expense.user_id == user_id,
            Expense.expense_date >= this_month_start,
        ).scalar() or 0

        last_month = db.query(func.sum(Expense.amount)).filter(
            Expense.user_id == user_id,
            Expense.expense_date >= last_month_start,
            Expense.expense_date < last_month_end,
        ).scalar() or 0

        change_pct = 0.0
        if float(last_month) > 0:
            change_pct = round(((float(this_month) - float(last_month)) / float(last_month)) * 100, 2)

        # By category
        cat_rows = (
            db.query(Category.name, func.sum(Expense.amount).label("total"))
            .join(Expense, Expense.category_id == Category.id, isouter=True)
            .filter(Expense.user_id == user_id, Expense.expense_date >= this_month_start)
            .group_by(Category.name)
            .all()
        )
        by_category = [{"category": r.name, "total": float(r.total)} for r in cat_rows]

        # By payment method
        pm_rows = (
            db.query(Expense.payment_method, func.sum(Expense.amount).label("total"))
            .filter(Expense.user_id == user_id, Expense.expense_date >= this_month_start)
            .group_by(Expense.payment_method)
            .all()
        )
        by_pm = [{"payment_method": r.payment_method or "Unknown", "total": float(r.total)} for r in pm_rows]

        recent = (
            db.query(Expense)
            .filter(Expense.user_id == user_id)
            .order_by(Expense.expense_date.desc())
            .limit(5)
            .all()
        )

        return {
            "total_this_month": float(this_month),
            "total_last_month": float(last_month),
            "change_percent": change_pct,
            "by_category": by_category,
            "recent": [_expense_to_dict(e) for e in recent],
            "by_payment_method": by_pm,
        }
