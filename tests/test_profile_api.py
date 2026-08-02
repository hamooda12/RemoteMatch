from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user import User

PROFILE_TEST_VALUE = "c" * 16


@pytest.fixture
def created_emails() -> Iterator[list[str]]:
    emails: list[str] = []
    yield emails

    if not emails:
        return

    engine = create_engine(get_settings().database_url)

    with Session(engine) as database:
        database.execute(delete(User).where(User.email.in_(emails)))
        database.commit()

    engine.dispose()


@pytest.fixture(autouse=True)
def clear_profile_cookies(client: TestClient) -> Iterator[None]:
    client.cookies.clear()
    yield
    client.cookies.clear()


def register_and_login(
    client: TestClient,
    email: str,
) -> str:
    registration_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "Profile User",
            "password": PROFILE_TEST_VALUE,
        },
    )
    assert registration_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": PROFILE_TEST_VALUE,
        },
    )
    assert login_response.status_code == 200

    return registration_response.json()["id"]


def test_profile_requires_authentication(client: TestClient) -> None:
    get_response = client.get("/api/v1/profile")
    put_response = client.put("/api/v1/profile", json={})

    assert get_response.status_code == 401
    assert put_response.status_code == 401


def test_create_update_and_get_profile(
    client: TestClient,
    created_emails: list[str],
) -> None:
    email = f"profile-{uuid4()}@example.com"
    created_emails.append(email)

    user_id = register_and_login(client, email)

    missing_response = client.get("/api/v1/profile")
    assert missing_response.status_code == 404

    payload = {
        "location": "  Hebron, Palestine  ",
        "timezone": "Asia/Hebron",
        "target_roles": [
            "Backend Engineer",
            "DevOps Engineer",
            "backend engineer",
        ],
        "experience_level": "junior",
        "minimum_salary": "2500.00",
        "salary_currency": "usd",
        "excluded_technologies": ["PHP", "php"],
        "availability": {
            "notice_period": "Two weeks",
        },
    }

    put_response = client.put("/api/v1/profile", json=payload)

    assert put_response.status_code == 200
    assert put_response.json()["user_id"] == user_id
    assert put_response.json()["location"] == "Hebron, Palestine"
    assert put_response.json()["target_roles"] == [
        "Backend Engineer",
        "DevOps Engineer",
    ]
    assert put_response.json()["experience_level"] == "junior"
    assert put_response.json()["minimum_salary"] == "2500.00"
    assert put_response.json()["salary_currency"] == "USD"
    assert put_response.json()["excluded_technologies"] == ["PHP"]

    get_response = client.get("/api/v1/profile")

    assert get_response.status_code == 200
    assert get_response.json() == put_response.json()

    replacement_response = client.put(
        "/api/v1/profile",
        json={
            "timezone": "UTC",
            "target_roles": ["Software Engineer"],
        },
    )

    assert replacement_response.status_code == 200
    assert replacement_response.json()["user_id"] == user_id
    assert replacement_response.json()["location"] is None
    assert replacement_response.json()["timezone"] == "UTC"
    assert replacement_response.json()["target_roles"] == ["Software Engineer"]
    assert replacement_response.json()["minimum_salary"] is None


def test_profiles_are_isolated_between_users(
    client: TestClient,
    created_emails: list[str],
) -> None:
    first_email = f"profile-first-{uuid4()}@example.com"
    second_email = f"profile-second-{uuid4()}@example.com"
    created_emails.extend([first_email, second_email])

    register_and_login(client, first_email)

    first_profile_response = client.put(
        "/api/v1/profile",
        json={
            "timezone": "Asia/Hebron",
            "target_roles": ["Backend Engineer"],
        },
    )
    assert first_profile_response.status_code == 200

    logout_response = client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 200

    register_and_login(client, second_email)

    second_profile_response = client.get("/api/v1/profile")

    assert second_profile_response.status_code == 404
    assert second_profile_response.json() == {"detail": "Profile not found."}
