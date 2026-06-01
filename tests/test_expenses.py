"""
Tests for expense CRUD, list/filter, and dashboard summary.
"""
import pytest
from datetime import date


EXPENSE_PAYLOAD = {
    "amount": 250.0,
    "expense_date": str(date.today()),
    "description": "Lunch",
    "merchant": "Swiggy",
    "payment_method": "upi",
    "currency": "INR",
}


def test_create_expense(client, auth_headers):
    response = client.post("/api/v1/expenses", json=EXPENSE_PAYLOAD, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["amount"] == 250.0
    assert data["merchant"] == "Swiggy"
    assert data["description"] == "Lunch"
    assert "id" in data
    assert "user_id" in data


def test_create_expense_invalid_amount(client, auth_headers):
    bad_payload = {**EXPENSE_PAYLOAD, "amount": "not-a-number"}
    response = client.post("/api/v1/expenses", json=bad_payload, headers=auth_headers)
    assert response.status_code == 422


def test_create_expense_missing_date(client, auth_headers):
    bad_payload = {k: v for k, v in EXPENSE_PAYLOAD.items() if k != "expense_date"}
    response = client.post("/api/v1/expenses", json=bad_payload, headers=auth_headers)
    assert response.status_code == 422


def test_list_expenses_empty(client, auth_headers):
    response = client.get("/api/v1/expenses", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert data["total"] == 0


def test_list_expenses_with_data(client, auth_headers):
    # Create two expenses first
    client.post("/api/v1/expenses", json=EXPENSE_PAYLOAD, headers=auth_headers)
    client.post(
        "/api/v1/expenses",
        json={**EXPENSE_PAYLOAD, "amount": 500.0, "description": "Dinner"},
        headers=auth_headers,
    )
    response = client.get("/api/v1/expenses", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    assert len(data["items"]) == 2
    amounts = {item["amount"] for item in data["items"]}
    assert 250.0 in amounts
    assert 500.0 in amounts


def test_get_expense_by_id(client, auth_headers):
    create_resp = client.post("/api/v1/expenses", json=EXPENSE_PAYLOAD, headers=auth_headers)
    expense_id = create_resp.json()["data"]["id"]

    response = client.get(f"/api/v1/expenses/{expense_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == expense_id
    assert data["amount"] == EXPENSE_PAYLOAD["amount"]
    assert data["merchant"] == EXPENSE_PAYLOAD["merchant"]


def test_get_expense_wrong_user(client, db):
    """A second user should not be able to see first user's expense."""
    # Register second user
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "User Two",
            "email": "user2@example.com",
            "phone": "+919111111111",
            "password": "UserTwo99!",
        },
    )
    login2 = client.post(
        "/api/v1/auth/login",
        json={"email": "user2@example.com", "password": "UserTwo99!"},
    )
    headers2 = {"Authorization": f"Bearer {login2.json()['access_token']}"}

    # Register and login first user
    client.post(
        "/api/v1/auth/register",
        json={
            "name": "User One",
            "email": "user1@example.com",
            "phone": "+919222222222",
            "password": "UserOne99!",
        },
    )
    login1 = client.post(
        "/api/v1/auth/login",
        json={"email": "user1@example.com", "password": "UserOne99!"},
    )
    headers1 = {"Authorization": f"Bearer {login1.json()['access_token']}"}

    # User1 creates an expense
    create_resp = client.post("/api/v1/expenses", json=EXPENSE_PAYLOAD, headers=headers1)
    expense_id = create_resp.json()["data"]["id"]

    # User2 tries to access it — should get 403 or 404
    response = client.get(f"/api/v1/expenses/{expense_id}", headers=headers2)
    assert response.status_code in (403, 404)


def test_update_expense(client, auth_headers):
    create_resp = client.post("/api/v1/expenses", json=EXPENSE_PAYLOAD, headers=auth_headers)
    expense_id = create_resp.json()["data"]["id"]

    update_resp = client.put(
        f"/api/v1/expenses/{expense_id}",
        json={"amount": 999.0, "description": "Updated description"},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()["data"]
    assert updated["amount"] == 999.0
    assert updated["description"] == "Updated description"
    assert updated["id"] == expense_id


def test_delete_expense(client, auth_headers):
    create_resp = client.post("/api/v1/expenses", json=EXPENSE_PAYLOAD, headers=auth_headers)
    expense_id = create_resp.json()["data"]["id"]

    delete_resp = client.delete(f"/api/v1/expenses/{expense_id}", headers=auth_headers)
    assert delete_resp.status_code == 200
    body = delete_resp.json()
    assert body["success"] is True

    # Confirm it's gone
    get_resp = client.get(f"/api/v1/expenses/{expense_id}", headers=auth_headers)
    assert get_resp.status_code == 404


def test_expense_list_filter_by_category(client, auth_headers, db):
    from app.models.category import Category
    from app.models.user import User

    # Get the current user's id
    me_resp = client.get("/api/v1/users/me", headers=auth_headers)
    user_id = me_resp.json()["data"]["id"]

    # Create a category for this user in the test db
    cat = Category(user_id=user_id, name="Food", icon="🍔", color="#FF0000", is_default=False)
    db.add(cat)
    db.flush()
    cat_id = str(cat.id)

    # Create one expense with category, one without
    client.post(
        "/api/v1/expenses",
        json={**EXPENSE_PAYLOAD, "category_id": cat_id},
        headers=auth_headers,
    )
    client.post("/api/v1/expenses", json=EXPENSE_PAYLOAD, headers=auth_headers)

    # Filter by category_id
    response = client.get(
        f"/api/v1/expenses?category_id={cat_id}", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["category_id"] == cat_id


def test_dashboard_summary(client, auth_headers):
    response = client.get("/api/v1/dashboard/summary", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    required_keys = [
        "total_this_month",
        "total_last_month",
        "change_percent",
        "recent_expenses",
        "top_categories",
        "active_budgets",
    ]
    for key in required_keys:
        assert key in data, f"Missing key in dashboard summary: {key}"
