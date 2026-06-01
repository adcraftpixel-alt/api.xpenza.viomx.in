from typing import List, Optional, Any
from pydantic import BaseModel


class DashboardSummaryResponse(BaseModel):
    total_this_month: float
    total_last_month: float
    change_percent: float
    monthly_income: Optional[float] = None
    savings_rate: Optional[float] = None
    active_budgets: int
    budget_alerts: int
    savings_goals: int
    goals_on_track: int
    recent_expenses: List[Any] = []
    top_categories: List[Any] = []
    budget_overview: List[Any] = []
