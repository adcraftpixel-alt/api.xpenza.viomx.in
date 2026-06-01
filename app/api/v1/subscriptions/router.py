from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user
from app.database import get_db
from app.api.v1.subscriptions.schemas import CreateSubscriptionRequest, UpdateSubscriptionRequest
from app.api.v1.subscriptions.service import SubscriptionService
from app.utils.response import success

router = APIRouter(tags=["Subscriptions"])
service = SubscriptionService()


@router.get("")
def list_subscriptions(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    subs = service.list(db, str(current_user.id))
    return success(subs)


@router.post("")
def create_subscription(
    data: CreateSubscriptionRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    sub = service.create(db, str(current_user.id), data)
    return success(sub, message="Subscription added")


@router.get("/renewals")
def get_upcoming_renewals(
    days: int = Query(default=30, ge=1, le=365, description="Look-ahead window in days"),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    renewals = service.get_renewals(db, str(current_user.id), days=days)
    return success(renewals)


@router.get("/total")
def get_total_cost(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    totals = service.get_total_monthly_cost(db, str(current_user.id))
    return success(totals)


@router.get("/{sub_id}")
def get_subscription(
    sub_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    sub = service.get_by_id(db, sub_id, str(current_user.id))
    return success(sub)


@router.put("/{sub_id}")
def update_subscription(
    sub_id: str,
    data: UpdateSubscriptionRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    sub = service.update(db, sub_id, str(current_user.id), data)
    return success(sub, message="Subscription updated")


@router.delete("/{sub_id}")
def delete_subscription(
    sub_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service.delete(db, sub_id, str(current_user.id))
    return success(None, message="Subscription removed")
