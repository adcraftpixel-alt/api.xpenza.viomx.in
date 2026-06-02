from fastapi import APIRouter, Depends, Query
from typing import Optional
from pydantic import BaseModel

class MonthlyAmountRequest(BaseModel):
    month: int
    year: int
    amount: float
    update_future: bool = True
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.budgets.schemas import CreateBudgetRequest, UpdateBudgetRequest
from app.api.v1.budgets.service import BudgetService
from app.utils.response import success

router = APIRouter(tags=["Budgets"])
service = BudgetService()


@router.post("")
def create_budget(
    data: CreateBudgetRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    budget = service.create(db, str(current_user.id), data)
    return success(budget, message="Budget created")


@router.get("")
def list_budgets(
    month: Optional[int] = Query(default=None, ge=1, le=12,
                                  description="Filter spent by month (1-12)"),
    year: Optional[int] = Query(default=None, description="Filter spent by year"),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    budgets = service.list(db, str(current_user.id), month=month, year=year)
    return success(budgets)


@router.get("/summary")
def get_budget_summary(current_user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    summary = service.get_summary(db, str(current_user.id))
    return success(summary)


@router.get("/alerts")
def get_budget_alerts(current_user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    alerts = service.get_alerts(db, str(current_user.id))
    return success(alerts)


@router.post("/recalculate")
def recalculate_budgets(current_user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    count = service.recalculate_all_for_user(db, str(current_user.id))
    return success({"recalculated": count}, message="Budgets recalculated")


@router.get("/{budget_id}")
def get_budget(
    budget_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    budget = service.get_by_id(db, budget_id, str(current_user.id))
    return success(budget)


@router.put("/{budget_id}")
def update_budget(
    budget_id: str,
    data: UpdateBudgetRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    budget = service.update(db, budget_id, str(current_user.id), data)
    return success(budget, message="Budget updated")


@router.put("/{budget_id}/monthly")
def set_monthly_amount(
    budget_id: str,
    data: MonthlyAmountRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Set a month-specific budget amount. Propagates to future months by default."""
    result = service.set_monthly_amount(
        db, budget_id, str(current_user.id),
        data.month, data.year, data.amount, data.update_future
    )
    return success(result, message="Budget amount updated for this month")


@router.delete("/{budget_id}")
def delete_budget(
    budget_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service.delete(db, budget_id, str(current_user.id))
    return success(None, message="Budget deleted")
