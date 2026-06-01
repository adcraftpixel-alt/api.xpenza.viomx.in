from typing import Optional, List, Any
from pydantic import BaseModel


class AdminStatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_expenses: int
    total_amount_tracked: float
    new_users_this_month: int


class AdminUserResponse(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    user_type: str
    is_active: bool
    is_verified: bool
    onboarding_done: bool
    created_at: str


class UpdateUserPlanRequest(BaseModel):
    plan_name: str


class SuspendUserRequest(BaseModel):
    reason: Optional[str] = None


class BroadcastNotificationRequest(BaseModel):
    title: str
    body: str
    type: str = "system"
    target: str = "all"  # all | verified | unverified
