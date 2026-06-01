from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
import uuid

from app.api.v1.content.schemas import CreateFAQRequest, UpdateFAQRequest


class FAQService:
    def list(self, db: Session, category: Optional[str] = None) -> List[dict]:
        try:
            if category:
                rows = db.execute(
                    text('SELECT * FROM faqs WHERE is_active=true AND category=:cat ORDER BY "order", id'),
                    {"cat": category},
                ).fetchall()
            else:
                rows = db.execute(
                    text('SELECT * FROM faqs WHERE is_active=true ORDER BY "order", id')
                ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "question": r.question,
                    "answer": r.answer,
                    "category": r.category,
                    "order": r.order,
                }
                for r in rows
            ]
        except Exception:
            return []

    def create(self, db: Session, data: CreateFAQRequest) -> dict:
        row_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO faqs (id, question, answer, category, "order", is_active, created_at)
                VALUES (:id, :q, :a, :cat, :ord, :active, NOW())
            """),
            {
                "id": row_id,
                "q": data.question,
                "a": data.answer,
                "cat": data.category,
                "ord": data.order,
                "active": data.is_active,
            },
        )
        db.commit()
        return {
            "id": row_id,
            "question": data.question,
            "answer": data.answer,
            "category": data.category,
            "order": data.order,
        }

    def update(self, db: Session, faq_id: str, data: UpdateFAQRequest) -> bool:
        updates = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
        if not updates:
            return True
        set_parts = [f'"{k}"=:{k}' for k in updates]
        updates["faq_id"] = faq_id
        db.execute(
            text(f"UPDATE faqs SET {', '.join(set_parts)} WHERE id=:faq_id"),
            updates,
        )
        db.commit()
        return True

    def delete(self, db: Session, faq_id: str) -> bool:
        db.execute(text("DELETE FROM faqs WHERE id=:id"), {"id": faq_id})
        db.commit()
        return True


faq_service = FAQService()
