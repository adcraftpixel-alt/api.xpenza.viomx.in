from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db

PLAN_LIMITS = {
    "Free": {
        "monthly_expenses": 50,
        "ocr_scans": 0,
        "ai_insights": False,
        "ai_chat": False,
        "sms_detection": False,
        "export_pdf": False,
        "export_csv": False,
        "budget_categories": 3,
    },
    "Pro": {
        "monthly_expenses": -1,  # unlimited
        "ocr_scans": 100,
        "ai_insights": True,
        "ai_chat": True,
        "sms_detection": True,
        "export_pdf": True,
        "export_csv": True,
        "budget_categories": -1,
    },
    "Business": {
        "monthly_expenses": -1,
        "ocr_scans": -1,
        "ai_insights": True,
        "ai_chat": True,
        "sms_detection": True,
        "export_pdf": True,
        "export_csv": True,
        "budget_categories": -1,
        "tax_reports": True,
    },
    "Enterprise": {
        "monthly_expenses": -1,
        "ocr_scans": -1,
        "ai_insights": True,
        "ai_chat": True,
        "sms_detection": True,
        "export_pdf": True,
        "export_csv": True,
        "budget_categories": -1,
        "tax_reports": True,
        "api_access": True,
    },
}


def get_user_plan(user_id: str, db: Session) -> str:
    result = db.execute(text("""
        SELECT bp.name FROM user_subscriptions us
        JOIN billing_plans bp ON bp.id = us.plan_id
        WHERE us.user_id = :uid AND us.status IN ('active', 'trialing')
        LIMIT 1
    """), {"uid": user_id}).fetchone()
    return result.name if result else "Free"


def get_plan_caps(plan_name: str, db: Session) -> dict:
    """Resolve enforcement caps for a plan.

    Prefers caps synced from the Control Hub (billing_plans.caps); falls back to
    the built-in defaults so enforcement still works if the Hub is unconfigured.
    """
    import json

    row = db.execute(
        text("SELECT caps FROM billing_plans WHERE name = :n LIMIT 1"),
        {"n": plan_name},
    ).fetchone()
    caps = row.caps if row else None
    if isinstance(caps, str):
        try:
            caps = json.loads(caps)
        except (ValueError, TypeError):
            caps = None
    if caps:
        return caps
    return PLAN_LIMITS.get(plan_name, PLAN_LIMITS["Free"])


def require_feature(feature: str):
    """
    Dependency that checks if user's plan has a feature.

    Usage:
        @router.get("/ai-chat")
        def ai_chat(
            current_user = Depends(require_feature("ai_chat")),
            db: Session = Depends(get_db),
        ):
            ...
    """
    def _dep(
        db: Session = Depends(get_db),
    ):
        from app.core.dependencies import get_current_active_user

        def _inner(current_user=Depends(get_current_active_user)):
            plan = get_user_plan(str(current_user.id), db)
            limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["Free"])
            if not limits.get(feature, False):
                raise HTTPException(
                    status_code=403,
                    detail=f"Feature '{feature}' requires a higher plan. Current plan: {plan}"
                )
            return current_user

        return _inner

    # FastAPI requires a callable with Depends, not a nested factory.
    # Use the class-based approach for clean dependency injection.
    from app.core.dependencies import get_current_active_user

    async def check(
        current_user=Depends(get_current_active_user),
        db: Session = Depends(get_db),
    ):
        plan = get_user_plan(str(current_user.id), db)
        limits = get_plan_caps(plan, db)
        if not limits.get(feature, False):
            raise HTTPException(
                status_code=403,
                detail=f"Feature '{feature}' requires a higher plan. Current plan: {plan}"
            )
        return current_user

    return check
