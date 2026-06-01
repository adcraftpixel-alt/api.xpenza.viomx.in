from typing import Optional, Any
from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: str
    title: Optional[str] = None
    body: Optional[str] = None
    type: Optional[str] = None
    is_read: bool
    data: Optional[Any] = None
    created_at: str


class PreferencesRequest(BaseModel):
    """Request schema for updating notification preferences.

    All fields are optional — only supplied fields are updated.
    """
    budget_alert: Optional[bool] = None
    large_expense_alert: Optional[bool] = None
    large_expense_threshold: Optional[float] = None
    weekly_summary: Optional[bool] = None
    ai_tips: Optional[bool] = None
    notification_frequency: Optional[str] = None
    # Legacy / extended fields kept for backward compat
    ai_insights_enabled: Optional[bool] = None
    ai_savings_enabled: Optional[bool] = None
    ai_budget_prediction: Optional[bool] = None
    sms_reading_enabled: Optional[bool] = None
    theme: Optional[str] = None
    language: Optional[str] = None


# Keep old name as alias so existing router import still works
UpdatePreferencesRequest = PreferencesRequest


class PreferencesResponse(BaseModel):
    """Full preferences response."""
    budget_alert: bool
    large_expense_alert: bool
    large_expense_threshold: float
    weekly_summary: bool
    ai_tips: bool
    notification_frequency: str
    ai_insights_enabled: bool
    ai_savings_enabled: bool
    ai_budget_prediction: bool
    sms_reading_enabled: bool
    theme: str
    language: str


class DeviceTokenRequest(BaseModel):
    token: str
    platform: str  # ios | android | web
