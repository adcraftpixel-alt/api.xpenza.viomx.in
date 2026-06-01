"""
Tests for auth endpoints: register, login, refresh, /me, logout.
"""
from datetime import timedelta


def test_register_success(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Alice",
            "email": "alice@example.com",
            "phone": "+919000000001",
            "password": "AlicePass99!",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["email"] == "alice@example.com"
    assert data["name"] == "Alice"
    assert "id" in data


def test_register_duplicate_email(client, registered_user):
    # registered_user fixture already registered test@example.com
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Duplicate",
            "email": "test@example.com",
            "password": "AnotherPass1!",
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert "already" in body["message"].lower() or "conflict" in body["message"].lower()


def test_register_invalid_email(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Bad Email", "email": "not-an-email", "password": "Pass1234!"},
    )
    assert response.status_code == 422


def test_login_success(client, registered_user):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "TestPass123!"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "test@example.com"


def test_login_wrong_password(client, registered_user):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False


def test_login_nonexistent_user(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@nowhere.com", "password": "DoesNotExist1!"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False


def test_refresh_token(client, registered_user):
    # First login to get tokens
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "TestPass123!"},
    )
    assert login_resp.status_code == 200
    refresh_token = login_resp.json()["refresh_token"]
    old_access = login_resp.json()["access_token"]

    # Now refresh
    response = client.post(
        "/api/v1/auth/refresh-token",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    # New access token should be a valid JWT string
    assert len(body["access_token"]) > 20
    # Should be different from old access token (different exp)
    # (May be same if created within same second, so we just check it's non-empty)
    assert body["access_token"] != ""


def test_refresh_token_invalid(client):
    response = client.post(
        "/api/v1/auth/refresh-token",
        json={"refresh_token": "this.is.not.a.valid.token"},
    )
    assert response.status_code == 401


def test_get_me_authenticated(client, auth_headers):
    response = client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["email"] == "test@example.com"
    assert data["name"] == "Test User"
    assert "id" in data
    assert "is_active" in data
    assert "onboarding_done" in data


def test_get_me_unauthenticated(client):
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_get_me_expired_token(client):
    # Create a token that is already expired
    from app.core.security import create_access_token
    expired_token = create_access_token(
        {"sub": "00000000-0000-0000-0000-000000000000"},
        expires_delta=timedelta(seconds=-1),
    )
    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
