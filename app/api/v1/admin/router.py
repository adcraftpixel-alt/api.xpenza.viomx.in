from fastapi import APIRouter, Depends, Query
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_admin_user
from app.core.exceptions import UnauthorizedError, ForbiddenError
from app.api.v1.admin.schemas import (
    UpdateUserPlanRequest, SuspendUserRequest, BroadcastNotificationRequest
)
from app.api.v1.admin.service import AdminService
from app.utils.response import success

router = APIRouter(tags=["Admin"])
service = AdminService()


class AdminLoginRequest(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def admin_login(data: AdminLoginRequest, db: Session = Depends(get_db)):
    from app.models.user import User
    from app.core.security import verify_password, create_access_token

    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password_hash or not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")
    if user.user_type != "admin":
        raise ForbiddenError("Admin access required")
    if not user.is_active:
        raise UnauthorizedError("Account is suspended")

    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "admin": {"email": user.email, "name": user.name}}


@router.get("/stats")
def get_stats(admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    stats = service.get_stats(db)
    return success(stats)


@router.get("/users")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    result = service.list_users(db, page, page_size, search)
    return success(result)


@router.get("/users/{user_id}")
def get_user(user_id: str, admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    user = service.get_user(db, user_id)
    return success(user)


@router.put("/users/{user_id}/plan")
def update_user_plan(
    user_id: str,
    data: UpdateUserPlanRequest,
    admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    service.update_user_plan(db, user_id, data)
    return success(None, message="User plan updated")


@router.put("/users/{user_id}/suspend")
def suspend_user(
    user_id: str,
    data: SuspendUserRequest = None,
    admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    service.suspend_user(db, user_id)
    return success(None, message="User suspended")


@router.put("/users/{user_id}/activate")
def activate_user(user_id: str, admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    service.activate_user(db, user_id)
    return success(None, message="User activated")


@router.delete("/users/{user_id}")
def delete_user(user_id: str, admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    service.delete_user(db, user_id)
    return success(None, message="User deleted")


@router.get("/billing/overview")
def billing_overview(admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    return success(service.get_billing_overview(db))


@router.get("/billing/subscriptions")
def billing_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    return success(service.list_subscriptions(db, page, page_size))


@router.get("/analytics/revenue")
def revenue_analytics(
    months: int = Query(6, ge=1, le=24),
    admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    return success(service.get_revenue_analytics(db, months))


@router.get("/analytics/usage")
def usage_analytics(admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    return success(service.get_usage_analytics(db))


@router.post("/broadcast")
def broadcast_notification(
    data: BroadcastNotificationRequest,
    admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    count = service.broadcast_notification(db, data)
    return success({"sent_to": count}, message=f"Notification sent to {count} users")
