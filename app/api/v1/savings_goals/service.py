from typing import List
from sqlalchemy.orm import Session
from app.models.savings_goal import SavingsGoal
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.api.v1.savings_goals.schemas import CreateSavingsGoalRequest, UpdateSavingsGoalRequest


def _goal_to_dict(g: SavingsGoal) -> dict:
    target = float(g.target_amount)
    current = float(g.current_amount)
    percent = round((current / target * 100), 2) if target > 0 else 0
    return {
        "id": str(g.id),
        "user_id": str(g.user_id),
        "name": g.name,
        "target_amount": target,
        "current_amount": current,
        "target_date": str(g.target_date) if g.target_date else None,
        "is_completed": g.is_completed,
        "percent_complete": percent,
    }


class SavingsGoalService:
    def create(self, db: Session, user_id: str, data: CreateSavingsGoalRequest) -> dict:
        goal = SavingsGoal(
            user_id=user_id,
            name=data.name,
            target_amount=data.target_amount,
            current_amount=data.current_amount,
            target_date=data.target_date,
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)
        return _goal_to_dict(goal)

    def list(self, db: Session, user_id: str) -> List[dict]:
        goals = db.query(SavingsGoal).filter(SavingsGoal.user_id == user_id).all()
        return [_goal_to_dict(g) for g in goals]

    def get_by_id(self, db: Session, goal_id: str, user_id: str) -> dict:
        g = db.query(SavingsGoal).filter(SavingsGoal.id == goal_id).first()
        if not g:
            raise NotFoundError("Savings goal not found")
        if str(g.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        return _goal_to_dict(g)

    def update(self, db: Session, goal_id: str, user_id: str, data: UpdateSavingsGoalRequest) -> dict:
        g = db.query(SavingsGoal).filter(SavingsGoal.id == goal_id).first()
        if not g:
            raise NotFoundError("Savings goal not found")
        if str(g.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(g, field, value)
        db.commit()
        db.refresh(g)
        return _goal_to_dict(g)

    def delete(self, db: Session, goal_id: str, user_id: str) -> bool:
        g = db.query(SavingsGoal).filter(SavingsGoal.id == goal_id).first()
        if not g:
            raise NotFoundError("Savings goal not found")
        if str(g.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        db.delete(g)
        db.commit()
        return True

    def add_contribution(self, db: Session, goal_id: str, user_id: str, amount: float) -> dict:
        g = db.query(SavingsGoal).filter(SavingsGoal.id == goal_id).first()
        if not g:
            raise NotFoundError("Savings goal not found")
        if str(g.user_id) != str(user_id):
            raise ForbiddenError("Access denied")
        if amount <= 0:
            raise ValidationError("Contribution amount must be positive")
        g.current_amount = float(g.current_amount) + amount
        if float(g.current_amount) >= float(g.target_amount):
            g.is_completed = True
        db.commit()
        db.refresh(g)
        return _goal_to_dict(g)
