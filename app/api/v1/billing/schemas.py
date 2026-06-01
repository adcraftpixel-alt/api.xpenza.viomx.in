from typing import Optional, Any, List
from datetime import datetime
from pydantic import BaseModel


class PlanResponse(BaseModel):
    id: str
    name: str
    price_monthly: Optional[float] = None
    price_yearly: Optional[float] = None
    features: Optional[Any] = None
    is_active: bool


class CheckoutRequest(BaseModel):
    plan_id: str
    interval: str = "monthly"  # monthly | yearly


class CheckoutResponse(BaseModel):
    client_secret: Optional[str] = None
    checkout_url: Optional[str] = None
    message: str = ""


class SubscriptionResponse(BaseModel):
    id: str
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    status: str
    current_period_start: Optional[str] = None
    current_period_end: Optional[str] = None
    cancel_at_period_end: bool


class InvoiceResponse(BaseModel):
    id: str
    amount: Optional[float] = None
    currency: str
    status: Optional[str] = None
    paid_at: Optional[str] = None
    invoice_pdf_url: Optional[str] = None
