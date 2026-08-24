import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List
from datetime import date, date as date_type
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.core.dependencies import get_current_active_user
from app.api.v1.expenses.schemas import CreateExpenseRequest, UpdateExpenseRequest
from app.api.v1.expenses.service import ExpenseService
from app.api.v1.expenses.sms_parser import sms_parser
from app.api.v1.expenses.quick_parser import parse_quick_text
from app.api.v1.expenses.ai_categorizer import suggest_category, learn_keyword
from app.config import settings
from app.core.idempotency import get_cached_response, store_response
from app.utils.response import success


class ParseSMSRequest(BaseModel):
    sms_body: str


class QuickParseRequest(BaseModel):
    text: str  # e.g. "250/- sugar, 50/- snacks"


class SuggestCategoryRequest(BaseModel):
    description: str  # expense description in any language
    family_group_id: Optional[str] = None  # set => resolve against the shared family tree


class LearnCategoryRequest(BaseModel):
    description: str
    category_id: str  # the node the user confirmed/corrected to
    family_group_id: Optional[str] = None


class QuickAddItem(BaseModel):
    amount: float
    description: str
    category_name: str  # category name string, we'll look up the ID
    payment_method: str = "cash"
    expense_date: Optional[date] = None
    category_id: Optional[str] = None  # explicit override — skips name lookup/AI when set


class BulkAddRequest(BaseModel):
    items: List[QuickAddItem]
    merchant: Optional[str] = None  # shared across all items, e.g. from a scanned receipt
    source: str = "quick_add"
    # Client-generated key, stable across retries of the same save action —
    # lets a retry after a client-side timeout replay the original batch
    # instead of re-creating every item.
    idempotency_key: Optional[str] = None

router = APIRouter(tags=["Expenses"])
service = ExpenseService()


@router.post("")
def create_expense(
    data: CreateExpenseRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    cached = get_cached_response(db, str(current_user.id), data.idempotency_key, "expenses.create")
    if cached is not None:
        return success(cached, message="Expense created")

    expense = service.create(db, str(current_user.id), data)
    store_response(db, str(current_user.id), data.idempotency_key, "expenses.create", expense)
    return success(expense, message="Expense created")


@router.post("/recategorize", summary="Re-run auto-categorization over existing expenses")
def recategorize_expenses(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Seed the default category tree (if missing) and re-tag existing expenses
    to specific categories/sub-items (e.g. Milk, Vegetables, Water) by matching
    their descriptions. Returns how many were updated."""
    result = service.recategorize(db, str(current_user.id))
    return success(result, message=f"Re-categorized {result['updated']} expense(s)")


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
    shared: bool = Query(default=False,
                         description="True = family expenses, False = personal"),
    cycle_month: Optional[str] = Query(
        default=None,
        description="YYYY-MM — restrict to that financial cycle (honours month_start_day)"),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    result = service.list(
        db, str(current_user.id), page, page_size,
        category_id, start_date, end_date, payment_method, min_amount, max_amount,
        shared=shared, cycle_month=cycle_month,
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


@router.post("/suggest-category")
def suggest_expense_category(
    request: SuggestCategoryRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Suggest the best matching category for an expense description in any language.

    Works with Hindi, Punjabi, Hinglish, English, or any mix.
    Matches against the user's own custom categories (not hardcoded names).

    Examples:
      "bijli ka bill"      → your Bills & Utilities category
      "doodh liya"         → your Groceries category
      "doctor ke paas gaya"→ your Health category
      "kiraya diya"        → your House Rent / EMI category
      "SIP kati aaj"       → your Investments category
    """
    result = suggest_category(
        request.description, str(current_user.id), db,
        family_group_id=request.family_group_id,
    )
    return success(result)


@router.post("/learn-category")
def learn_expense_category(
    request: LearnCategoryRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Record a user's category correction as a keyword alias so the same item
    name resolves to that category instantly next time (self-learning).
    """
    saved = learn_keyword(
        db, request.description, request.category_id, str(current_user.id),
        family_group_id=request.family_group_id,
    )
    return success({"learned": saved})


_GROQ_API_KEY = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
_GROQ_MODEL = "llama-3.3-70b-versatile"


@router.post("/ai-parse")
def ai_parse_expenses(
    request: QuickParseRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Use Groq LLM to parse conversational speech (any language) into structured
    expense items, matched against the user's real custom categories.
    """
    import json
    import httpx
    from app.models.category import Category as CategoryModel

    # Fetch user's real category names for the prompt
    user_cats = (
        db.query(CategoryModel)
        .filter(CategoryModel.user_id == current_user.id, CategoryModel.parent_id.is_(None))
        .all()
    )
    cat_names = [c.name for c in user_cats] or [
        "Groceries", "Food & Dining", "Transport", "Shopping",
        "Bills & Utilities", "Health", "Entertainment", "Others",
    ]
    cat_list_str = ", ".join(cat_names)

    system_prompt = (
        "You are a multilingual expense parser for an Indian finance app. "
        "Parse spoken or typed text (Hindi, Punjabi, Hinglish, English, or any mix) "
        "into individual expense items. "
        "Return ONLY a raw JSON array — no markdown, no explanation. "
        f"Format: [{{\"amount\": 10.0, \"description\": \"Milk\", \"category\": \"Groceries\"}}] "
        f"Valid categories (use exactly one): {cat_list_str}. "
        "Rules: "
        "- Understand Hindi/Punjabi: 'doodh'=milk, 'chai'=tea, 'petrol'=fuel, 'dawai'=medicine, "
        "'kiraya'=rent, 'bijli'=electricity, 'kapde'=clothes, 'khana'=food; "
        "- Extract every item+amount pair; ignore filler words; "
        "- Amounts: 'Rs 10', '₹100', '150 rupees', or number before/after item name; "
        "- Description: title-case, concise (1-3 words in English); "
        "- Skip items with 0 or unclear amount."
    )

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
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Parse: {request.text}"},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 600,
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()

        start = raw.find('[')
        end = raw.rfind(']') + 1
        if start < 0 or end <= start:
            raise ValueError("No JSON array in response")

        parsed = json.loads(raw[start:end])
        items = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            amt  = float(item.get("amount") or 0)
            desc = str(item.get("description") or "").strip()
            cat  = str(item.get("category") or cat_names[0]).strip()
            if amt > 0 and desc:
                # Attach real category_id by name lookup
                matched = next(
                    (c for c in user_cats if c.name.lower() == cat.lower()), None
                )
                items.append({
                    "amount":      amt,
                    "description": desc,
                    "category":    cat,
                    "category_id": str(matched.id) if matched else None,
                })

        if items:
            return success(items, message=f"AI parsed {len(items)} item(s)")

    except Exception:
        pass

    # Fallback to local regex parser
    items = parse_quick_text(request.text)
    return success(items, message=f"Parsed {len(items)} item(s)")


def _resolve_bulk_category_id(item: QuickAddItem, user_id: str) -> Optional[str]:
    """Resolve one bulk-create item's category on its own short-lived DB
    session, so it's safe to call concurrently across items (SQLAlchemy
    sessions aren't thread-safe to share). Mirrors the same exact-name-match
    → AI-categorizer fallback that used to run inline in the request's own
    session."""
    if item.category_id:
        # Caller already resolved/overrode the category (e.g. user manually
        # corrected it before saving) — skip the name lookup entirely.
        return item.category_id

    from app.models.category import Category

    session = SessionLocal()
    try:
        cat = (
            session.query(Category)
            .filter(
                Category.user_id == user_id,
                Category.name.ilike(f'%{item.category_name}%'),
            )
            .first()
        )
        if cat:
            return str(cat.id)

        suggestion = suggest_category(item.description, user_id, session)
        return suggestion.get("category_id")
    finally:
        session.close()


@router.post("/bulk-create")
def bulk_create_expenses(
    request: BulkAddRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create multiple expenses at once from quick-add."""
    cached = get_cached_response(
        db, str(current_user.id), request.idempotency_key, "expenses.bulk_create"
    )
    if cached is not None:
        return success(cached, message=f"Created {len(cached)} expense(s)")

    created = []
    today = date_type.today()

    # Category resolution can fall through to a Groq LLM call per item (up to
    # ~8s each — see ai_categorizer.py) when there's no keyword match. Doing
    # that sequentially for, say, an 8-item receipt meant up to ~64s before
    # any expense was even inserted — well past the client's save timeout,
    # which is exactly what caused the timeout+duplicate bug this endpoint
    # now also guards against via idempotency_key above. Resolving all items
    # concurrently turns that worst case into roughly one LLM round trip's
    # worth of wall-clock time. Each worker gets its own short-lived DB
    # session (SQLAlchemy sessions aren't safe to share across threads) — the
    # request's own `db` session is only touched afterward, sequentially, for
    # the actual (fast) inserts.
    with ThreadPoolExecutor(max_workers=min(len(request.items), 6) or 1) as pool:
        category_ids = list(pool.map(
            lambda item: _resolve_bulk_category_id(item, str(current_user.id)),
            request.items,
        ))

    for item, category_id in zip(request.items, category_ids):
        data = CreateExpenseRequest(
            amount=item.amount,
            description=item.description,
            category_id=category_id,
            payment_method=item.payment_method,
            expense_date=item.expense_date or today,
            currency="INR",
            source=request.source,
            merchant=request.merchant,
        )
        expense = service.create(db, str(current_user.id), data)
        created.append(expense)

    store_response(
        db, str(current_user.id), request.idempotency_key, "expenses.bulk_create", created
    )
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
