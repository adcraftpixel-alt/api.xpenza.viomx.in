"""VIOMX Control Hub service API — read-only, protected by X-Service-Key."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.dependencies import verify_service_key
from app.api.v1.service.service import service_feed
from app.utils.response import success

router = APIRouter(tags=["Service"], dependencies=[Depends(verify_service_key)])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    return success(service_feed.stats(db))


@router.get("/users")
def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = None,
    db: Session = Depends(get_db),
):
    return success(service_feed.list_users(db, page=page, limit=limit, search=search))


@router.get("/payments")
def get_payments(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return success(service_feed.list_payments(db, page=page, limit=limit))


@router.get("/payment-methods")
def get_payment_methods(db: Session = Depends(get_db)):
    return success(service_feed.payment_methods(db))


@router.post("/users/{user_id}/block")
def block_user(user_id: str, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    try:
        return success(service_feed.set_user_active(db, user_id, active=False),
                       message="User blocked")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/users/{user_id}/unblock")
def unblock_user(user_id: str, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    try:
        return success(service_feed.set_user_active(db, user_id, active=True),
                       message="User unblocked")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/funding")
def get_funding(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return success(service_feed.funding(db, page=page, limit=limit))
