from pydantic import BaseModel
from typing import List, Optional


class DailyDataPoint(BaseModel):
    date: str
    amount: float


class CategoryDataPoint(BaseModel):
    category: str
    amount: float
    percentage: float
    color: Optional[str] = None


class MonthlyAnalyticsResponse(BaseModel):
    month: str
    daily_data: List[DailyDataPoint]
    total: float
    avg_daily: float
    prev_month_total: float
    change_pct: float


class CategoryAnalyticsResponse(BaseModel):
    period: str
    categories: List[CategoryDataPoint]
    total: float


class IncomeVsExpensePoint(BaseModel):
    month: str
    income: float
    expenses: float
    savings: float


class WeeklyDataPoint(BaseModel):
    week_label: str
    amount: float


class YearlyAnalyticsResponse(BaseModel):
    year: int
    monthly_data: List[dict]
    total: float
    avg_monthly: float
