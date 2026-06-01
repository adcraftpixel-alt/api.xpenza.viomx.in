from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.ai.schemas import ChatRequest
from app.api.v1.ai.service import AIService
from app.api.v1.ai import health_service
from app.utils.response import success

router = APIRouter(tags=["AI"])
service = AIService()


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

@router.get("/insights")
def get_insights(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Return a list of AI-generated insights for the current user."""
    insights = service.get_insights(db, str(current_user.id))
    return success(insights)


# ---------------------------------------------------------------------------
# Health score
# ---------------------------------------------------------------------------

@router.get("/health-score")
def get_health_score(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Calculate and return the user's financial health score (0-100).
    Delegates to health_service.get_health_score for a savings-rate /
    budget-adherence / expense-consistency composite.
    """
    score = health_service.get_health_score(db, str(current_user.id), current_user)
    return success(score)


# ---------------------------------------------------------------------------
# Savings advice
# ---------------------------------------------------------------------------

@router.get("/savings-advice")
def get_savings_advice(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Return personalised savings tips based on this month's spending."""
    advice = service.get_savings_advice(db, str(current_user.id), current_user)
    return success(advice)


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------

@router.get("/predictions")
def get_predictions(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Predict next month's spend using a 3-month moving average.
    Delegates to health_service.get_predictions.
    """
    predictions = health_service.get_predictions(db, str(current_user.id))
    return success(predictions)


# ---------------------------------------------------------------------------
# Subscription detection
# ---------------------------------------------------------------------------

@router.get("/subscription-detect")
def detect_subscriptions(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Detect recurring subscription-like charges from expense history.
    Returns both already-tracked subscriptions and newly detected patterns.
    Delegates to health_service.detect_subscriptions.
    """
    subs = health_service.detect_subscriptions(db, str(current_user.id))
    return success(subs)


# ---------------------------------------------------------------------------
# AI Chat
# ---------------------------------------------------------------------------

@router.post("/chat")
def chat(
    data: ChatRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Send a message to the AI finance assistant and receive a reply."""
    response = service.chat(db, str(current_user.id), data.message)
    return success(response)


@router.get("/chat/history")
def chat_history(
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Retrieve the user's AI chat history (most recent first, paginated)."""
    history = service.get_chat_history(db, str(current_user.id), limit)
    return success(history)
