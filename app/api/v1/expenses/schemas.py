from typing import Optional, List, Any
from datetime import date
from pydantic import BaseModel


class CreateExpenseRequest(BaseModel):
    amount: float
    category_id: Optional[str] = None
    payment_method: Optional[str] = None
    expense_date: date
    merchant: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    source: str = "manual"
    is_recurring: bool = False
    recurring_interval: Optional[str] = None
    currency: str = "INR"
    ai_category: Optional[str] = None
    family_group_id: Optional[str] = None
    # Family only: attribute this spend to a specific member (their user_id).
    # Defaults to the creator when omitted.
    spent_by_user_id: Optional[str] = None


class UpdateExpenseRequest(BaseModel):
    amount: Optional[float] = None
    category_id: Optional[str] = None
    payment_method: Optional[str] = None
    expense_date: Optional[date] = None
    merchant: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    is_recurring: Optional[bool] = None
    recurring_interval: Optional[str] = None


class ExpenseResponse(BaseModel):
    id: str
    user_id: str
    category_id: Optional[str] = None
    amount: float
    currency: str
    description: Optional[str] = None
    merchant: Optional[str] = None
    payment_method: Optional[str] = None
    expense_date: date
    is_recurring: bool
    recurring_interval: Optional[str] = None
    receipt_url: Optional[str] = None
    tags: Optional[List[str]] = None
    source: str
    ai_category: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class ExpenseListResponse(BaseModel):
    items: List[ExpenseResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ExpenseSummaryResponse(BaseModel):
    total_this_month: float
    total_last_month: float
    change_percent: float
    by_category: List[dict]
    recent: List[dict]
    by_payment_method: List[dict]
