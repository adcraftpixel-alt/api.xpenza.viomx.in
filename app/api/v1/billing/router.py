from fastapi import APIRouter, Depends, Request, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.models.user import User
from app.api.v1.billing.service import billing_service
from app.api.v1.billing.stripe_service import stripe_service
from app.utils.response import success
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["Billing"])


class CheckoutRequest(BaseModel):
    plan_id: str
    interval: str = "monthly"  # monthly | yearly


@router.get("/plans")
def get_plans(db: Session = Depends(get_db)):
    return success(billing_service.get_plans(db))


@router.post("/checkout")
def create_checkout(
    request: CheckoutRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    from fastapi import HTTPException
    try:
        result = billing_service.create_checkout(current_user, request.plan_id, request.interval, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return success(result)


@router.get("/subscription")
def get_subscription(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    return success(billing_service.get_current_subscription(str(current_user.id), db))


@router.delete("/subscription")
def cancel_subscription(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    from fastapi import HTTPException
    try:
        result = billing_service.cancel_subscription(str(current_user.id), db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return success(result)


@router.get("/invoices")
def get_invoices(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    return success(billing_service.get_invoices(current_user, db))


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
    db: Session = Depends(get_db)
):
    payload = await request.body()

    # In development without Stripe configured, accept test events directly
    from app.config import settings
    if not settings.STRIPE_SECRET_KEY or settings.STRIPE_SECRET_KEY == "sk_test_placeholder":
        import json
        try:
            event = json.loads(payload)
            billing_service.handle_webhook(event.get("type", ""), event.get("data", {}), db)
            return {"received": True}
        except Exception:
            return {"received": True}

    try:
        event = stripe_service.construct_webhook_event(payload, stripe_signature or "")
        billing_service.handle_webhook(event["type"], event["data"], db)
        return {"received": True}
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
