import os
from typing import Optional, List
from datetime import date, date as date_type
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.expenses.schemas import CreateExpenseRequest, UpdateExpenseRequest
from app.api.v1.expenses.service import ExpenseService
from app.api.v1.expenses.sms_parser import sms_parser
from app.api.v1.expenses.quick_parser import parse_quick_text
from app.utils.response import success


class ParseSMSRequest(BaseModel):
    sms_body: str


class QuickParseRequest(BaseModel):
    text: str  # e.g. "250/- sugar, 50/- snacks"


class QuickAddItem(BaseModel):
    amount: float
    description: str
    category_name: str  # category name string, we'll look up the ID
    payment_method: str = "cash"
    expense_date: Optional[date] = None


class BulkAddRequest(BaseModel):
    items: List[QuickAddItem]

router = APIRouter(tags=["Expenses"])
service = ExpenseService()


@router.post("")
def create_expense(
    data: CreateExpenseRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    expense = service.create(db, str(current_user.id), data)
    return success(expense, message="Expense created")


@router.get("/summary")
def get_summary(current_user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    summary = service.get_summary(db, str(current_user.id))
    return success(summary)


@router.get("/search")
def search_expenses(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    result = service.search(db, str(current_user.id), q, page, page_size)
    return success(result)


@router.get("/recurring")
def get_recurring(current_user=Depends(get_current_active_user), db: Session = Depends(get_db)):
    items = service.get_recurring(db, str(current_user.id))
    return success(items)


@router.get("")
def list_expenses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    payment_method: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    result = service.list(
        db, str(current_user.id), page, page_size,
        category_id, start_date, end_date, payment_method, min_amount, max_amount
    )
    return success(result)


@router.post("/quick-parse")
def quick_parse(
    request: QuickParseRequest,
    current_user=Depends(get_current_active_user),
):
    """Parse natural language text into expense items with auto-categorization."""
    items = parse_quick_text(request.text)
    return success(items, message=f"Parsed {len(items)} item(s)")


_GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
_GROQ_MODEL = "llama-3.1-8b-instant"

_GROQ_SYSTEM = (
    "You are an expense parser for an Indian expense app. "
    "Parse spoken or typed text into individual expense items. "
    "Return ONLY a raw JSON array — no markdown, no explanation. "
    "Format: [{\"amount\": 10.0, \"description\": \"Milk\", \"category\": \"Groceries\"}] "
    "Valid categories (use exactly one): "
    "Groceries, Food & Dining, Transport, Shopping, Bills & Utilities, "
    "Health, Entertainment, Personal Care, Education, Others. "
    "Rules: extract every item+amount pair; ignore filler words like 'and','well','also'; "
    "amounts can be written as 'Rs 10', 'Rs. 50', '₹100', '150 rupees', or just a number before an item; "
    "description should be title-case and concise (1-3 words); "
    "if amount is 0 or unclear skip that item."
)


@router.post("/ai-parse")
def ai_parse_expenses(
    request: QuickParseRequest,
    current_user=Depends(get_current_active_user),
):
    """Use Groq LLM to parse conversational speech into structured expense items."""
    import json
    import httpx

    try:
        with httpx.Client(timeout=12.0) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {_GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": _GROQ_SYSTEM},
                        {"role": "user", "content": f"Parse: {request.text}"},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 600,
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()

        # Extract JSON array (model may wrap in markdown fences)
        start = raw.find('[')
        end = raw.rfind(']') + 1
        if start < 0 or end <= start:
            raise ValueError("No JSON array in response")

        parsed = json.loads(raw[start:end])
        items = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            amt = float(item.get("amount") or 0)
            desc = str(item.get("description") or "").strip()
            cat = str(item.get("category") or "Others").strip()
            if amt > 0 and desc:
                items.append({"amount": amt, "description": desc, "category": cat})

        if items:
            return success(items, message=f"AI parsed {len(items)} item(s)")

    except Exception:
        pass

    # Fallback to local regex parser
    items = parse_quick_text(request.text)
    return success(items, message=f"Parsed {len(items)} item(s)")


@router.post("/bulk-create")
def bulk_create_expenses(
    request: BulkAddRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create multiple expenses at once from quick-add."""
    from app.models.category import Category

    created = []
    today = date_type.today()

    for item in request.items:
        # Find matching category by name for this user, or fall back to first category
        cat = db.query(Category).filter(
            Category.user_id == current_user.id,
            Category.name.ilike(f'%{item.category_name}%')
        ).first()

        if not cat:
            cat = db.query(Category).filter(
                Category.user_id == current_user.id
            ).first()

        data = CreateExpenseRequest(
            amount=item.amount,
            description=item.description,
            category_id=str(cat.id) if cat else None,
            payment_method=item.payment_method,
            expense_date=item.expense_date or today,
            currency="INR",
            source="quick_add",
        )
        expense = service.create(db, str(current_user.id), data)
        created.append(expense)

    return success(created, message=f"Created {len(created)} expense(s)")


@router.get("/{expense_id}")
def get_expense(
    expense_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    expense = service.get_by_id(db, expense_id, str(current_user.id))
    return success(expense)


@router.put("/{expense_id}")
def update_expense(
    expense_id: str,
    data: UpdateExpenseRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    expense = service.update(db, expense_id, str(current_user.id), data)
    return success(expense, message="Expense updated")


@router.delete("/{expense_id}")
def delete_expense(
    expense_id: str,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service.delete(db, expense_id, str(current_user.id))
    return success(None, message="Expense deleted")


@router.post("/parse-sms")
def parse_sms(
    request: ParseSMSRequest,
    current_user=Depends(get_current_active_user),
):
    result = sms_parser.parse(request.sms_body)
    if result:
        return success(result, "Transaction detected from SMS")
    return success(None, "No transaction detected in SMS")
