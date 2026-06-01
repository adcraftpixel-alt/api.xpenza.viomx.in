import csv
import io
import uuid
import json
import logging
from calendar import month_abbr
from datetime import datetime, date, timedelta
from typing import Optional, List
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy import text, func, extract

from app.models.expense import Expense
from app.models.category import Category
from app.models.user import User
from app.api.v1.reports.schemas import ExportRequest

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("/tmp/aifinanceos_reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Categories considered tax-deductible
TAX_DEDUCTIBLE_CATEGORIES = {"health", "education", "insurance"}


class ReportService:
    # ── Monthly report ─────────────────────────────────────────────────────────

    def get_monthly_report(self, db: Session, user_id: str, month: int, year: int) -> dict:
        """
        Returns a breakdown of expenses for a single calendar month.
        Income is taken from the user's monthly_income field.
        """
        # All expenses for the month
        expenses = (
            db.query(Expense)
            .filter(
                Expense.user_id == user_id,
                extract("month", Expense.expense_date) == month,
                extract("year", Expense.expense_date) == year,
            )
            .all()
        )

        total_expense = float(sum(e.amount for e in expenses))
        expense_count = len(expenses)

        # Monthly income from user profile
        user = db.query(User).filter(User.id == user_id).first()
        total_income = float(user.monthly_income or 0) if user else 0.0
        saved = total_income - total_expense

        # Days in month for avg_daily
        import calendar as _cal
        _, days_in_month = _cal.monthrange(year, month)
        avg_daily = round(total_expense / days_in_month, 2)

        # Category breakdown with category names resolved
        cat_totals: dict[str, float] = {}
        for e in expenses:
            if e.category_id:
                cat_obj = db.query(Category).filter(Category.id == e.category_id).first()
                cat_name = cat_obj.name if cat_obj else "Uncategorized"
            else:
                cat_name = "Uncategorized"
            cat_totals[cat_name] = cat_totals.get(cat_name, 0.0) + float(e.amount)

        category_breakdown = []
        for cat, amt in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
            pct = round((amt / total_expense * 100) if total_expense else 0.0, 2)
            category_breakdown.append({"category": cat, "amount": round(amt, 2), "percent": pct})

        # Top merchant by spend
        merchant_totals: dict[str, float] = {}
        for e in expenses:
            if e.merchant:
                merchant_totals[e.merchant] = merchant_totals.get(e.merchant, 0.0) + float(e.amount)
        top_merchant = max(merchant_totals, key=merchant_totals.get) if merchant_totals else None

        return {
            "month": month,
            "year": year,
            "total_expense": round(total_expense, 2),
            "total_income": round(total_income, 2),
            "saved": round(saved, 2),
            "category_breakdown": category_breakdown,
            "top_merchant": top_merchant,
            "expense_count": expense_count,
            "avg_daily": avg_daily,
        }

    # ── Yearly report ──────────────────────────────────────────────────────────

    def get_yearly_report(self, db: Session, user_id: str, year: int) -> dict:
        """
        Returns month-by-month summary for a full calendar year.
        """
        user = db.query(User).filter(User.id == user_id).first()
        monthly_income = float(user.monthly_income or 0) if user else 0.0

        # Aggregate expenses by month using SQLAlchemy extract
        rows = (
            db.query(
                extract("month", Expense.expense_date).label("m"),
                func.coalesce(func.sum(Expense.amount), 0).label("total"),
            )
            .filter(
                Expense.user_id == user_id,
                extract("year", Expense.expense_date) == year,
            )
            .group_by("m")
            .all()
        )

        monthly_map: dict[int, float] = {int(r.m): float(r.total) for r in rows}

        months_list = []
        total_expense = 0.0
        total_income = 0.0

        for m in range(1, 13):
            exp = round(monthly_map.get(m, 0.0), 2)
            inc = round(monthly_income, 2)
            saved = round(inc - exp, 2)
            total_expense += exp
            total_income += inc
            months_list.append(
                {
                    "month": m,
                    "month_name": month_abbr[m],
                    "expense": exp,
                    "income": inc,
                    "saved": saved,
                }
            )

        total_saved = round(total_income - total_expense, 2)

        # Best month = highest saved; worst = highest expense
        best = max(months_list, key=lambda x: x["saved"]) if months_list else None
        worst = max(months_list, key=lambda x: x["expense"]) if months_list else None

        best_month = f"{month_abbr[best['month']]} {year}" if best else None
        worst_month = f"{month_abbr[worst['month']]} {year}" if worst else None

        return {
            "year": year,
            "total_expense": round(total_expense, 2),
            "total_income": round(total_income, 2),
            "total_saved": total_saved,
            "months": months_list,
            "best_month": best_month,
            "worst_month": worst_month,
        }

    # ── Tax report ─────────────────────────────────────────────────────────────

    def get_tax_report(self, db: Session, user_id: str, year: int) -> dict:
        """
        Returns expenses whose category name falls in TAX_DEDUCTIBLE_CATEGORIES.
        Categories matched case-insensitively.
        """
        expenses = (
            db.query(Expense)
            .join(Category, Expense.category_id == Category.id, isouter=True)
            .filter(
                Expense.user_id == user_id,
                extract("year", Expense.expense_date) == year,
            )
            .all()
        )

        items: list[dict] = []
        total_deductible = 0.0

        for e in expenses:
            cat_obj = None
            if e.category_id:
                cat_obj = db.query(Category).filter(Category.id == e.category_id).first()

            cat_name = cat_obj.name if cat_obj else ""
            if cat_name.lower() not in TAX_DEDUCTIBLE_CATEGORIES:
                continue

            amt = float(e.amount)
            total_deductible += amt
            description = e.description or e.merchant or f"{cat_name} expense"
            items.append(
                {
                    "category": cat_name,
                    "amount": round(amt, 2),
                    "description": description,
                }
            )

        return {
            "year": year,
            "total_deductible": round(total_deductible, 2),
            "items": sorted(items, key=lambda x: x["amount"], reverse=True),
        }

    # ── Export ─────────────────────────────────────────────────────────────────

    def export_report(
        self,
        db: Session,
        user_id: str,
        format: str,
        period: str,
        month: Optional[int] = None,
        year: Optional[int] = None,
    ) -> dict:
        """
        Generates a report file for the requested period + format and returns
        a download URL.  PDF/Excel return a mock URL; CSV is fully generated.
        """
        now = datetime.utcnow()
        year = year or now.year
        month = month or now.month

        report_id = uuid.uuid4().hex
        filename = f"report_{user_id[:8]}_{period}_{year}"
        if period == "monthly":
            filename += f"_{month:02d}"
        filename += f".{format}"

        expires_at = (now + timedelta(hours=24)).isoformat() + "Z"

        if format == "csv":
            filepath = REPORTS_DIR / filename
            self._write_csv_report(db, user_id, period, month, year, filepath)
            download_url = f"/api/v1/reports/download/{filename}"
        else:
            # Mock URL for PDF / Excel (would be generated by a background task)
            download_url = (
                f"https://storage.aifinanceos.com/reports/{filename}"
                f"?token={report_id}&expires={int(now.timestamp() + 86400)}"
            )

        return {
            "download_url": download_url,
            "filename": filename,
            "expires_at": expires_at,
        }

    def _write_csv_report(
        self,
        db: Session,
        user_id: str,
        period: str,
        month: int,
        year: int,
        filepath: Path,
    ) -> None:
        """Write a CSV file to disk for the requested period."""
        query = db.query(Expense).filter(
            Expense.user_id == user_id,
            extract("year", Expense.expense_date) == year,
        )
        if period == "monthly":
            query = query.filter(extract("month", Expense.expense_date) == month)

        expenses = query.order_by(Expense.expense_date.desc()).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["Date", "Amount", "Currency", "Merchant", "Description",
             "Category", "Payment Method", "Tags", "Notes", "Source"]
        )
        for e in expenses:
            cat_name = ""
            if e.category_id:
                cat_obj = db.query(Category).filter(Category.id == e.category_id).first()
                cat_name = cat_obj.name if cat_obj else ""
            writer.writerow([
                str(e.expense_date),
                float(e.amount),
                e.currency,
                e.merchant or "",
                e.description or "",
                cat_name,
                e.payment_method or "",
                ",".join(e.tags) if e.tags else "",
                e.notes or "",
                e.source,
            ])

        filepath.write_text(output.getvalue(), encoding="utf-8")

    # ── Legacy helpers (kept for backward compat) ──────────────────────────────

    def export(self, db: Session, user_id: str, data: ExportRequest) -> dict:
        query = db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.expense_date >= data.start_date,
            Expense.expense_date <= data.end_date,
        )
        if data.categories:
            query = query.join(
                Category, Expense.category_id == Category.id, isouter=True
            ).filter(Category.name.in_(data.categories))
        expenses = query.order_by(Expense.expense_date.desc()).all()

        report_id = uuid.uuid4().hex
        filename = f"{report_id}.{data.format}"
        filepath = REPORTS_DIR / filename

        if data.format == "csv":
            content = self._generate_csv_from_models(expenses)
            filepath.write_text(content, encoding="utf-8")
        elif data.format == "json":
            content = self._generate_json(expenses)
            filepath.write_text(content, encoding="utf-8")
        else:
            content = self._generate_csv_from_models(expenses)
            filename = f"{report_id}.csv"
            filepath = REPORTS_DIR / filename
            filepath.write_text(content, encoding="utf-8")

        return {
            "report_id": report_id,
            "format": data.format,
            "download_url": f"/api/v1/reports/download/{filename}",
            "generated_at": datetime.utcnow().isoformat(),
            "row_count": len(expenses),
        }

    def _generate_csv_from_models(self, expenses) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date", "Amount", "Currency", "Merchant", "Description",
            "Category", "Payment Method", "Tags", "Notes", "Source",
        ])
        for e in expenses:
            writer.writerow([
                str(e.expense_date),
                float(e.amount),
                e.currency,
                e.merchant or "",
                e.description or "",
                str(e.category_id) if e.category_id else "",
                e.payment_method or "",
                ",".join(e.tags) if e.tags else "",
                e.notes or "",
                e.source,
            ])
        return output.getvalue()

    def _generate_json(self, expenses) -> str:
        data = [
            {
                "id": str(e.id),
                "date": str(e.expense_date),
                "amount": float(e.amount),
                "currency": e.currency,
                "merchant": e.merchant,
                "description": e.description,
                "category_id": str(e.category_id) if e.category_id else None,
                "payment_method": e.payment_method,
                "tags": e.tags,
                "notes": e.notes,
                "source": e.source,
            }
            for e in expenses
        ]
        return json.dumps(data, indent=2)

    def generate_csv(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
        categories: list,
        db: Session,
    ) -> bytes:
        rows = db.execute(
            text("""
                SELECT e.expense_date, e.amount, e.merchant, e.description,
                       COALESCE(c.name, 'Uncategorized') as category,
                       e.payment_method, e.source, e.notes
                FROM expenses e
                LEFT JOIN categories c ON c.id = e.category_id
                WHERE e.user_id = :uid
                  AND e.expense_date >= :start AND e.expense_date <= :end
                ORDER BY e.expense_date DESC
            """),
            {"uid": user_id, "start": start_date, "end": end_date},
        ).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date", "Amount", "Category", "Merchant", "Description",
            "Payment Method", "Source", "Notes",
        ])
        for row in rows:
            writer.writerow([
                str(row.expense_date), f"{row.amount:.2f}",
                row.category, row.merchant or "",
                row.description or "", row.payment_method or "",
                row.source or "", row.notes or "",
            ])

        return output.getvalue().encode("utf-8")

    def generate_summary(
        self, user_id: str, start_date: str, end_date: str, db: Session
    ) -> dict:
        total = db.execute(
            text("""
                SELECT COALESCE(SUM(amount), 0) FROM expenses
                WHERE user_id = :uid AND expense_date >= :start AND expense_date <= :end
            """),
            {"uid": user_id, "start": start_date, "end": end_date},
        ).scalar()

        by_category = db.execute(
            text("""
                SELECT COALESCE(c.name, 'Uncategorized') as cat, SUM(e.amount) as total
                FROM expenses e LEFT JOIN categories c ON c.id = e.category_id
                WHERE e.user_id = :uid AND e.expense_date >= :start AND e.expense_date <= :end
                GROUP BY c.name ORDER BY total DESC
            """),
            {"uid": user_id, "start": start_date, "end": end_date},
        ).fetchall()

        return {
            "total": float(total or 0),
            "period": f"{start_date} to {end_date}",
            "by_category": [{"category": r.cat, "amount": float(r.total)} for r in by_category],
        }

    def get_history(self, user_id: str) -> List[dict]:
        reports = []
        try:
            for f in REPORTS_DIR.iterdir():
                if f.is_file():
                    reports.append({
                        "filename": f.name,
                        "download_url": f"/api/v1/reports/download/{f.name}",
                        "size_bytes": f.stat().st_size,
                    })
        except Exception as e:
            logger.warning(f"Could not list reports: {e}")
        return reports[:20]


report_service = ReportService()
