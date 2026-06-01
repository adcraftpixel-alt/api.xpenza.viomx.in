from typing import Optional
from datetime import date
from pydantic import BaseModel


class CreateBudgetRequest(BaseModel):
    name: str
    amount: float
    category_id: Optional[str] = None
    period: str = "monthly"
    start_date: date
    end_date: Optional[date] = None
    alert_threshold: float = 80.0
    is_shared: bool = False


class UpdateBudgetRequest(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    category_id: Optional[str] = None
    period: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    alert_threshold: Optional[float] = None
    is_active: Optional[bool] = None


class BudgetResponse(BaseModel):
    id: str
    user_id: str
    category_id: Optional[str] = None
    name: str
    amount: float
    spent: float
    period: str
    start_date: date
    end_date: Optional[date] = None
    alert_threshold: float
    is_active: bool
    percent_used: float

    class Config:
        from_attributes = True
