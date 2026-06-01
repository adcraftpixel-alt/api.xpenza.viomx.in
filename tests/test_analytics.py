"""
Tests for analytics, SMS parsing, and CSV export endpoints.
"""
import pytest
from datetime import date


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def test_monthly_analytics_empty(client, auth_headers):
    """Monthly analytics should return 200 with a daily_data list even when empty."""
    response = client.get("/api/v1/analytics/monthly", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert "daily_data" in data
    assert isinstance(data["daily_data"], list)
    assert len(data["daily_data"]) > 0  # at least one day in current month
    assert "total" in data
    assert "month" in data
    assert data["total"] == 0.0


def test_monthly_analytics_with_month_param(client, auth_headers):
    """Passing an explicit month parameter should work."""
    response = client.get("/api/v1/analytics/monthly?month=2025-01", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["month"] == "2025-01"
    assert len(data["daily_data"]) == 31  # January has 31 days


def test_categories_analytics_empty(client, auth_headers):
    """Categories analytics should return 200 with empty categories list when no data."""
    response = client.get("/api/v1/analytics/categories", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert "categories" in data
    assert isinstance(data["categories"], list)
    assert data["total"] == 0.0


def test_income_vs_expense(client, auth_headers):
    """Income vs expense endpoint returns a list of 6 months by default."""
    response = client.get("/api/v1/analytics/income-vs-expense", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert isinstance(data, list)
    assert len(data) == 6
    for item in data:
        assert "month" in item
        assert "income" in item
        assert "expenses" in item
        assert "savings" in item


def test_income_vs_expense_custom_months(client, auth_headers):
    """Requesting 3 months should return 3 items."""
    response = client.get("/api/v1/analytics/income-vs-expense?months=3", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 3


def test_yearly_analytics(client, auth_headers):
    """Yearly analytics should return monthly breakdown with 12 items."""
    response = client.get("/api/v1/analytics/yearly", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert "monthly_data" in data
    assert len(data["monthly_data"]) == 12
    assert "total" in data
    assert "year" in data


def test_payment_methods_empty(client, auth_headers):
    """Payment methods analytics returns an empty list when no data."""
    response = client.get("/api/v1/analytics/payment-methods", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)


# ---------------------------------------------------------------------------
# SMS parsing
# ---------------------------------------------------------------------------

def test_sms_parse_valid(client, auth_headers):
    """A real bank SMS should be parsed and return amount + merchant."""
    sms = "Rs.500.00 debited from your HDFC Bank A/c XX1234 at SWIGGY on 15/05/2025. Avl bal: Rs.12345.67"
    response = client.post(
        "/api/v1/expenses/parse-sms",
        json={"sms_body": sms},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data is not None
    assert data["amount"] == 500.0
    assert "SWIGGY" in data["merchant"].upper() or data["merchant"] != ""
    assert data["source"] == "sms"
    assert "confidence" in data


def test_sms_parse_upi(client, auth_headers):
    """UPI payment SMS should be parsed correctly."""
    sms = "INR 250.00 paid to Zomato via UPI on 20/05/2025. Ref No 123456789"
    response = client.post(
        "/api/v1/expenses/parse-sms",
        json={"sms_body": sms},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data is not None
    assert data["amount"] == 250.0
    assert data["payment_method"] == "upi"


def test_sms_parse_no_transaction(client, auth_headers):
    """SMS with no debit transaction should return None data."""
    sms = "Your account has been credited with Rs.5000. Available balance: Rs.25000."
    response = client.post(
        "/api/v1/expenses/parse-sms",
        json={"sms_body": sms},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] is None


def test_sms_parse_otp_ignored(client, auth_headers):
    """OTP SMS should not be parsed as a transaction."""
    sms = "Your OTP for transaction is 123456. Do not share with anyone."
    response = client.post(
        "/api/v1/expenses/parse-sms",
        json={"sms_body": sms},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"] is None


def test_sms_parse_missing_body(client, auth_headers):
    """Missing sms_body should return 422."""
    response = client.post(
        "/api/v1/expenses/parse-sms",
        json={},
        headers=auth_headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

def test_csv_export(client, auth_headers):
    """CSV export should return CSV content with correct headers."""
    today = str(date.today())
    year = date.today().year
    payload = {
        "format": "csv",
        "start_date": f"{year}-01-01",
        "end_date": today,
    }
    response = client.post("/api/v1/reports/export", json=payload, headers=auth_headers)
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    content = response.content.decode("utf-8")
    # Should contain CSV header row
    assert "Date" in content
    assert "Amount" in content
    assert "Category" in content


def test_reports_summary(client, auth_headers):
    """Reports summary should return total and by_category."""
    response = client.get("/api/v1/reports/summary", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert "total" in data
    assert "period" in data
    assert "by_category" in data
    assert isinstance(data["by_category"], list)
