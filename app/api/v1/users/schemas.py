from typing import Literal, Optional, List, Any
from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    user_type: str
    monthly_income: Optional[float] = None
    currency: str
    avatar_url: Optional[str] = None
    is_verified: bool
    is_active: bool
    onboarding_done: bool
    biometric_enabled: bool

    class Config:
        from_attributes = True


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    monthly_income: Optional[float] = None
    currency: Optional[str] = None
    biometric_enabled: Optional[bool] = None
    user_type: Optional[str] = None
    onboarding_done: Optional[bool] = None
    avatar_url: Optional[str] = None


class OnboardingRequest(BaseModel):
    user_type: str = "personal"
    monthly_income: Optional[float] = None
    currency: str = "INR"
    selected_categories: List[str] = []
    goals: List[str] = []
    notification_frequency: str = "daily"
    ai_insights_enabled: bool = True
    sms_reading_enabled: bool = False
    income_type: str = "salary"           # salary | variable | business
    payment_methods: List[str] = []       # upi, credit_card, debit_card, cash, net_banking
    alert_threshold: float = 80.0         # 70 | 80 | 90
    pain_point: str = ""                  # user's main financial challenge


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

class PreferencesRequest(BaseModel):
    """All fields are optional — only supplied fields are updated."""

    notification_frequency: Optional[Literal["daily", "weekly", "off"]] = None
    ai_insights_enabled: Optional[bool] = None
    ai_savings_enabled: Optional[bool] = None
    ai_budget_prediction: Optional[bool] = None
    sms_reading_enabled: Optional[bool] = None
    theme: Optional[Literal["light", "dark"]] = None
    language: Optional[Literal["en", "hi"]] = None
    month_start_day: Optional[int] = Field(default=None, ge=1, le=28)


class PreferencesResponse(BaseModel):
    id: str
    user_id: str
    notification_frequency: Literal["daily", "weekly", "off"] = "daily"
    ai_insights_enabled: bool = True
    ai_savings_enabled: bool = True
    ai_budget_prediction: bool = True
    sms_reading_enabled: bool = False
    theme: Literal["light", "dark"] = "light"
    language: Literal["en", "hi"] = "en"
    month_start_day: int = 1
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Onboarding status
# ---------------------------------------------------------------------------

class OnboardingStatusResponse(BaseModel):
    onboarding_done: bool
    user_exists: bool
    # True once GRACE_PERIOD_DAYS have passed since registration with no
    # active/trialing paid subscription — the app must then block "Skip" on
    # the trial screen and require activation.
    grace_period_expired: bool = False
    # TRIAL_DAYS minus days already elapsed since registration, floored at 0.
    # The grace period and the paid trial share one clock anchored to
    # created_at, so activating late shortens the trial instead of granting
    # a fresh TRIAL_DAYS from the moment of activation.
    trial_days_remaining: int = 0
