import os
import subprocess

# Set test env vars BEFORE importing anything from app
TEST_DB_URL = "postgresql://manjitparmar@localhost:5432/aifinanceos_test"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["JWT_SECRET"] = "test-secret-key-for-testing"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"  # db 1 for tests
os.environ["ENVIRONMENT"] = "test"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db

engine = create_engine(TEST_DB_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    # Create test DB if not exists (connect to postgres maintenance DB)
    subprocess.run(
        ["psql", "-U", "manjitparmar", "-d", "postgres", "-c", "CREATE DATABASE aifinanceos_test;"],
        capture_output=True,
    )
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def registered_user(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "phone": "+919876543210",
            "password": "TestPass123!",
        },
    )
    assert response.status_code == 200, f"Register failed: {response.text}"
    return response.json()


@pytest.fixture
def auth_headers(client, registered_user):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "TestPass123!"},
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
