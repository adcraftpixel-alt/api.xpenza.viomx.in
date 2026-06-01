from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.content.service import faq_service
from app.api.v1.content.schemas import CreateFAQRequest, UpdateFAQRequest
from app.utils.response import success

router = APIRouter(tags=["Content"])


@router.get("/faqs")
def list_faqs(category: Optional[str] = Query(None), db: Session = Depends(get_db)):
    return success(faq_service.list(db, category))


@router.post("/faqs")
def create_faq(
    data: CreateFAQRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if not getattr(user, "is_admin", False):
        from fastapi import HTTPException

        raise HTTPException(403, "Admin only")
    return success(faq_service.create(db, data))


@router.put("/faqs/{faq_id}")
def update_faq(
    faq_id: str,
    data: UpdateFAQRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if not getattr(user, "is_admin", False):
        from fastapi import HTTPException

        raise HTTPException(403, "Admin only")
    faq_service.update(db, faq_id, data)
    return success(None, message="FAQ updated")


@router.delete("/faqs/{faq_id}")
def delete_faq(
    faq_id: str,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if not getattr(user, "is_admin", False):
        from fastapi import HTTPException

        raise HTTPException(403, "Admin only")
    faq_service.delete(db, faq_id)
    return success(None, message="FAQ deleted")
