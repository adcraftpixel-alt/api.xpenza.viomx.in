from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.core.security import decode_token
from app.core.exceptions import UnauthorizedError, ForbiddenError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def verify_service_key(x_service_key: str = Header(None, alias="X-Service-Key")):
    """Machine-to-machine auth for the VIOMX Control Hub service API.

    Requires SERVICE_API_KEY to be configured; a missing/blank config means the
    service API is disabled (no implicit open access).
    """
    expected = settings.SERVICE_API_KEY
    if not expected:
        raise ForbiddenError("Service API is not enabled")
    if not x_service_key or x_service_key != expected:
        raise UnauthorizedError("Invalid service key")
    return True


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    from app.models.user import User

    payload = decode_token(token)
    user_id: str = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token payload")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise UnauthorizedError("User not found")
    return user


def get_current_active_user(current_user=Depends(get_current_user)):
    if not current_user.is_active:
        raise ForbiddenError("Account is inactive")
    return current_user


def require_plan(plan: str):
    def dependency(current_user=Depends(get_current_active_user), db: Session = Depends(get_db)):
        from app.models.billing import UserSubscription, BillingPlan

        sub = (
            db.query(UserSubscription)
            .filter(
                UserSubscription.user_id == current_user.id,
                UserSubscription.status == "active",
            )
            .first()
        )
        if not sub:
            raise ForbiddenError(f"Plan '{plan}' required. No active subscription found.")

        billing_plan = db.query(BillingPlan).filter(BillingPlan.id == sub.plan_id).first()
        if not billing_plan or billing_plan.name.lower() != plan.lower():
            raise ForbiddenError(f"Plan '{plan}' required.")
        return current_user

    return dependency


def get_current_admin_user(current_user=Depends(get_current_active_user)):
    if current_user.user_type != "admin":
        raise ForbiddenError("Admin access required")
    return current_user
