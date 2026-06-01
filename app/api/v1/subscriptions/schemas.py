from typing import Optional
from datetime import date
from pydantic import BaseModel, field_validator


VALID_BILLING_CYCLES = {"monthly", "yearly", "weekly"}


class CreateSubscriptionRequest(BaseModel):
    name: str
    amount: float
    billing_cycle: str = "monthly"
    next_renewal: Optional[date] = None
    category: Optional[str] = None

    @field_validator("billing_cycle")
    @classmethod
    def validate_billing_cycle(cls, v: str) -> str:
        if v not in VALID_BILLING_CYCLES:
            raise ValueError(f"billing_cycle must be one of: {', '.join(sorted(VALID_BILLING_CYCLES))}")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount must be greater than 0")
        return v


class UpdateSubscriptionRequest(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    billing_cycle: Optional[str] = None
    next_renewal: Optional[date] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("billing_cycle")
    @classmethod
    def validate_billing_cycle(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_BILLING_CYCLES:
            raise ValueError(f"billing_cycle must be one of: {', '.join(sorted(VALID_BILLING_CYCLES))}")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("amount must be greater than 0")
        return v


class SubscriptionResponse(BaseModel):
    id: str
    user_id: str
    name: str
    amount: float
    billing_cycle: str
    next_renewal: Optional[date] = None
    category: Optional[str] = None
    is_active: bool
    detected_by_ai: bool
    created_at: Optional[str] = None
    days_until_renewal: Optional[int] = None

    class Config:
        from_attributes = True
