"""
Tests for budget CRUD, alerts, and spent recalculation.
"""
from datetime import date


BUDGET_PAYLOAD = {
    "name": "Monthly Food Budget",
    "amount": 5000.0,
    "period": "monthly",
    "start_date": str(date.today().replace(day=1)),
    "alert_threshold": 80.0,
}


def test_create_budget(client, auth_headers):
    response = client.post("/api/v1/budgets", json=BUDGET_PAYLOAD, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["name"] == "Monthly Food Budget"
    assert data["amount"] == 5000.0
    assert data["spent"] == 0.0
    assert data["percent_used"] == 0.0
    assert "id" in data


def test_list_budgets(client, auth_headers):
    # Create two budgets
    client.post("/api/v1/budgets", json=BUDGET_PAYLOAD, headers=auth_headers)
    client.post(
        "/api/v1/budgets",
        json={**BUDGET_PAYLOAD, "name": "Travel Budget", "amount": 10000.0},
        headers=auth_headers,
    )
    response = client.get("/api/v1/budgets", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    items = body["data"]
    assert isinstance(items, list)
    assert len(items) == 2
    names = {b["name"] for b in items}
    assert "Monthly Food Budget" in names
    assert "Travel Budget" in names


def test_budget_alerts_empty(client, auth_headers):
    # Create a budget that is not near threshold
    client.post("/api/v1/budgets", json=BUDGET_PAYLOAD, headers=auth_headers)
    response = client.get("/api/v1/budgets/alerts", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    # No expenses added, so spent = 0, no alerts
    assert body["data"] == []


def test_budget_spent_updates_on_expense(client, auth_headers, db):
    """
    Create a budget without a category filter (covers all expenses for the user
    within the date range). Then add an expense. Recalculate and confirm
    budget.spent has increased.
    """
    from app.models.budget import Budget
    from app.models.expense import Expense

    # 1. Create budget
    budget_resp = client.post(
        "/api/v1/budgets", json=BUDGET_PAYLOAD, headers=auth_headers
    )
    assert budget_resp.status_code == 200
    budget_id = budget_resp.json()["data"]["id"]

    # 2. Get current user id
    me = client.get("/api/v1/users/me", headers=auth_headers).json()["data"]
    user_id = me["id"]

    # 3. Add an expense
    expense_resp = client.post(
        "/api/v1/expenses",
        json={
            "amount": 1500.0,
            "expense_date": str(date.today()),
            "description": "Groceries",
            "payment_method": "card",
            "currency": "INR",
        },
        headers=auth_headers,
    )
    assert expense_resp.status_code == 200

    # 4. Trigger recalculation via budget service directly
    from app.api.v1.budgets.service import BudgetService
    service = BudgetService()
    new_spent = service.recalculate_spent(budget_id, db)
    db.commit()

    # 5. Fetch budget and check spent updated
    response = client.get(f"/api/v1/budgets/{budget_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["spent"] >= 1500.0, f"Expected spent >= 1500, got {data['spent']}"
    assert data["percent_used"] > 0.0
