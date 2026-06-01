from typing import Optional
from datetime import date
from pydantic import BaseModel


class CreateSavingsGoalRequest(BaseModel):
    name: str
    target_amount: float
    current_amount: float = 0.0
    target_date: Optional[date] = None


class UpdateSavingsGoalRequest(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[float] = None
    target_date: Optional[date] = None


class ContributionRequest(BaseModel):
    amount: float


class SavingsGoalResponse(BaseModel):
    id: str
    user_id: str
    name: str
    target_amount: float
    current_amount: float
    target_date: Optional[date] = None
    is_completed: bool
    percent_complete: float

    class Config:
        from_attributes = True
