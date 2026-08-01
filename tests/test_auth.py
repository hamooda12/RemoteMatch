from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user import User


@pytest.fixture
def registration_email() -> Iterator[str]:
    email = f"user-{uuid4()}@example.com"
    yield email

    engine = create_engine(get_settings().database_url)

    with Session(engine) as database:
        database.execute(delete(User).where(User.email == email))
        database.commit()

    engine.dispose()


@pytest.fixture(autouse=True)
def clear_auth_cookies(client: TestClient) -> Iterator[None]:
    client.cookies.clear()
    yield
    client.cookies.clear()


def test_register_user_and_reject_duplicate(
    client: TestClient,
    registration_email: str,
) -> None:
    payload = {
        "email": registration_email,
        "display_name": "Test User",
        "password": "Correct-Horse-Battery-42",
    }

    response = client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 201
    assert response.json()["email"] == registration_email
    assert response.json()["display_name"] == "Test User"
    assert "password" not in response.json()
    assert "password_hash" not in response.json()

    duplicate_response = client.post(
        "/api/v1/auth/register",
        json=payload,
    )

    assert duplicate_response.status_code == 409


def test_register_rejects_short_password(
    client: TestClient,
    registration_email: str,
) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": registration_email,
            "display_name": "Test User",
            "password": "short",
        },
    )

    assert response.status_code == 422


def test_login_current_user_and_logout(
    client: TestClient,
    registration_email: str,
) -> None:
    password = "Correct-Horse-Battery-42"

    registration_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": registration_email,
            "display_name": "Test User",
            "password": password,
        },
    )
    assert registration_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": registration_email,
            "password": password,
        },
    )

    assert login_response.status_code == 200
    assert login_response.json()["email"] == registration_email
    assert get_settings().session_cookie_name in client.cookies

    current_user_response = client.get("/api/v1/auth/me")

    assert current_user_response.status_code == 200
    assert current_user_response.json()["email"] == registration_email

    logout_response = client.post("/api/v1/auth/logout")

    assert logout_response.status_code == 200
    assert logout_response.json() == {"message": "Logged out successfully."}

    unauthenticated_response = client.get("/api/v1/auth/me")
    assert unauthenticated_response.status_code == 401


def test_login_rejects_invalid_credentials(
    client: TestClient,
    registration_email: str,
) -> None:
    registration_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": registration_email,
            "display_name": "Test User",
            "password": "Correct-Horse-Battery-42",
        },
    )
    assert registration_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": registration_email,
            "password": "Wrong-Password-123",
        },
    )

    assert login_response.status_code == 401
    assert login_response.json() == {"detail": "Invalid email or password."}
