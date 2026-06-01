from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid

from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.support.schemas import CreateTicketRequest
from app.utils.response import success

router = APIRouter(tags=["Support"])


@router.post("/tickets")
def create_ticket(
    data: CreateTicketRequest,
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    ticket_id = str(uuid.uuid4())
    try:
        db.execute(
            text("""
                INSERT INTO support_tickets (id, user_id, subject, message, category, status, created_at)
                VALUES (:id, :uid, :subj, :msg, :cat, 'open', NOW())
            """),
            {
                "id": ticket_id,
                "uid": str(user.id),
                "subj": data.subject,
                "msg": data.message,
                "cat": data.category,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
    return success({"id": ticket_id, "status": "open"}, message="Support ticket submitted")


@router.get("/tickets")
def list_tickets(
    user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    try:
        rows = db.execute(
            text("""
                SELECT id, subject, category, status, created_at FROM support_tickets
                WHERE user_id=:uid ORDER BY created_at DESC LIMIT 20
            """),
            {"uid": str(user.id)},
        ).fetchall()
        return success(
            [
                {
                    "id": str(r.id),
                    "subject": r.subject,
                    "category": r.category,
                    "status": r.status,
                    "created_at": str(r.created_at),
                }
                for r in rows
            ]
        )
    except Exception:
        return success([])
