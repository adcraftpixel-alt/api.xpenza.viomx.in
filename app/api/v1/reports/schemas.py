from typing import Optional, List
from datetime import date
from pydantic import BaseModel, field_validator


# ── Export ────────────────────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    format: str = "csv"          # pdf | csv | excel
    period: str = "monthly"      # monthly | yearly
    month: Optional[int] = None  # 1–12; required when period="monthly"
    year: Optional[int] = None   # e.g. 2026
    # Legacy fields kept so the existing /export endpoint still works
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    categories: Optional[List[str]] = None

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        allowed = {"pdf", "csv", "excel"}
        if v not in allowed:
            raise ValueError(f"format must be one of {allowed}")
        return v

    @field_validator("period")
    @classmethod
    def validate_period(cls, v: str) -> str:
        allowed = {"monthly", "yearly"}
        if v not in allowed:
            raise ValueError(f"period must be one of {allowed}")
        return v


class ExportResponse(BaseModel):
    download_url: str
    filename: str
    expires_at: str


# ── Monthly report ────────────────────────────────────────────────────────────

class CategoryBreakdown(BaseModel):
    category: str
    amount: float
    percent: float


class MonthlyReportResponse(BaseModel):
    month: int
    year: int
    total_expense: float
    total_income: float
    saved: float
    category_breakdown: List[CategoryBreakdown]
    top_merchant: Optional[str]
    expense_count: int
    avg_daily: float


# ── Yearly report ─────────────────────────────────────────────────────────────

class MonthSummary(BaseModel):
    month: int
    month_name: str
    expense: float
    income: float
    saved: float


class YearlyReportResponse(BaseModel):
    year: int
    total_expense: float
    total_income: float
    total_saved: float
    months: List[MonthSummary]
    best_month: Optional[str]
    worst_month: Optional[str]


# ── Tax report ────────────────────────────────────────────────────────────────

class TaxLineItem(BaseModel):
    category: str
    amount: float
    description: str


class TaxReportResponse(BaseModel):
    year: int
    total_deductible: float
    items: List[TaxLineItem]


# ── Legacy (kept for backward compat with existing /export endpoint) ──────────

class ReportResponse(BaseModel):
    report_id: str
    format: str
    download_url: str
    generated_at: str
    row_count: int
