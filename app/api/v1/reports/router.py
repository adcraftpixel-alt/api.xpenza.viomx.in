from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
import io

from sqlalchemy.orm import Session

from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.reports.schemas import ExportRequest, ExportResponse
from app.api.v1.reports.service import ReportService, REPORTS_DIR, report_service
from app.utils.response import success

router = APIRouter(tags=["Reports"])
service = ReportService()


# ── New structured report endpoints ───────────────────────────────────────────

@router.get("/monthly")
def get_monthly_report(
    month: int = Query(default=None, ge=1, le=12, description="Month number (1–12)"),
    year: int = Query(default=None, description="4-digit year, e.g. 2026"),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns a full monthly expense report for the given month/year.
    Defaults to the current month and year when not supplied.
    """
    now = datetime.utcnow()
    month = month or now.month
    year = year or now.year
    data = service.get_monthly_report(db, str(current_user.id), month, year)
    return success(data, message="Monthly report fetched")


@router.get("/yearly")
def get_yearly_report(
    year: int = Query(default=None, description="4-digit year, e.g. 2026"),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns a month-by-month summary for the given year.
    Defaults to the current year when not supplied.
    """
    now = datetime.utcnow()
    year = year or now.year
    data = service.get_yearly_report(db, str(current_user.id), year)
    return success(data, message="Yearly report fetched")


@router.get("/tax")
def get_tax_report(
    year: int = Query(default=None, description="4-digit year, e.g. 2026"),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Returns tax-deductible expenses (Health, Education, Insurance) for the year.
    """
    now = datetime.utcnow()
    year = year or now.year
    data = service.get_tax_report(db, str(current_user.id), year)
    return success(data, message="Tax report fetched")


# ── Export endpoint (extended to support new period-based export) ──────────────

@router.post("/export")
def export_report(
    data: ExportRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Export a report.

    New usage — supply `format`, `period`, and optionally `month` / `year`:
      { "format": "csv", "period": "monthly", "month": 5, "year": 2026 }

    Legacy usage (start_date + end_date) is still supported; in that case
    a streaming CSV response is returned for CSV format, or a file-based
    export for other formats.
    """
    # ---- Legacy path: start_date / end_date supplied -------------------------
    if data.start_date and data.end_date:
        if data.format == "csv":
            csv_bytes = report_service.generate_csv(
                user_id=str(current_user.id),
                start_date=str(data.start_date),
                end_date=str(data.end_date),
                categories=data.categories or [],
                db=db,
            )
            return StreamingResponse(
                io.BytesIO(csv_bytes),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=expenses.csv"},
            )
        result = service.export(db, str(current_user.id), data)
        return success(result, message="Report generated")

    # ---- New path: period-based export ---------------------------------------
    now = datetime.utcnow()
    result = service.export_report(
        db=db,
        user_id=str(current_user.id),
        format=data.format,
        period=data.period,
        month=data.month or now.month,
        year=data.year or now.year,
    )
    return success(result, message="Report export initiated")


# ── Legacy / utility endpoints (unchanged) ────────────────────────────────────

@router.get("/summary")
def get_summary(
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    if not start_date:
        start_date = f"{now.year}-{now.month:02d}-01"
    if not end_date:
        end_date = now.strftime("%Y-%m-%d")
    data = report_service.generate_summary(str(current_user.id), start_date, end_date, db)
    return success(data)


@router.get("/history")
def report_history(current_user=Depends(get_current_active_user)):
    history = service.get_history(str(current_user.id))
    return success(history)


@router.get("/download/{filename}")
def download_report(filename: str, current_user=Depends(get_current_active_user)):
    filepath = REPORTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Report file not found")
    return FileResponse(path=str(filepath), filename=filename)
