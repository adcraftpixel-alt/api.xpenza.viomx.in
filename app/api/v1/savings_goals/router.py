from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.savings_goals.schemas import (
    CreateSavingsGoalRequest, UpdateSavingsGoalRequest, ContributionRequest
)
from app.api.v1.savings_goals.service import SavingsGoalService
from app.utils.response import success

router = APIRouter(tags=["Savings Goals"])
service = SavingsGoalService()


@router.post("")
def create_goal(
    data: CreateSavingsGoalRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    goal = service.create(db, str(current_user.id), data)
    return success(goal, message="Savings goal created")


@router.get("")
def list_goals(current_user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    goals = service.list(db, str(current_user.id))
    return success(goals)


@router.get("/{goal_id}")
def get_goal(
    goal_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    goal = service.get_by_id(db, goal_id, str(current_user.id))
    return success(goal)


@router.put("/{goal_id}")
def update_goal(
    goal_id: str,
    data: UpdateSavingsGoalRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    goal = service.update(db, goal_id, str(current_user.id), data)
    return success(goal, message="Goal updated")


@router.post("/{goal_id}/contribute")
def add_contribution(
    goal_id: str,
    data: ContributionRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    goal = service.add_contribution(db, goal_id, str(current_user.id), data.amount)
    return success(goal, message="Contribution added")


@router.delete("/{goal_id}")
def delete_goal(
    goal_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service.delete(db, goal_id, str(current_user.id))
    return success(None, message="Goal deleted")
