from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.job import Job
from app.models.user import User

APPLICATION_TEST_PASSWORD = "t" * 16


@dataclass
class ApplicationCleanup:
    emails: list[str] = field(default_factory=list)
    job_ids: list[UUID] = field(default_factory=list)


@pytest.fixture(autouse=True)
def clear_application_cookies(
    client: TestClient,
) -> Iterator[None]:
    client.cookies.clear()
    yield
    client.cookies.clear()


@pytest.fixture
def application_cleanup(
    client: TestClient,
) -> Iterator[ApplicationCleanup]:
    cleanup = ApplicationCleanup()
    yield cleanup

    client.cookies.clear()

    engine = create_engine(get_settings().database_url)

    with Session(engine) as database:
        if cleanup.emails:
            database.execute(
                delete(User).where(
                    User.email.in_(cleanup.emails),
                )
            )
            database.flush()

        if cleanup.job_ids:
            database.execute(
                delete(Job).where(
                    Job.id.in_(cleanup.job_ids),
                )
            )

        database.commit()

    engine.dispose()


def register_and_login(
    client: TestClient,
    cleanup: ApplicationCleanup,
) -> UUID:
    email = f"application-{uuid4()}@example.com"
    cleanup.emails.append(email)

    registration_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "Application User",
            "password": APPLICATION_TEST_PASSWORD,
        },
    )
    assert registration_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": APPLICATION_TEST_PASSWORD,
        },
    )
    assert login_response.status_code == 200

    return UUID(registration_response.json()["id"])


def csrf_headers(
    client: TestClient,
) -> dict[str, str]:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200

    return {
        "X-CSRF-Token": response.json()["csrf_token"],
    }


def create_test_job(
    cleanup: ApplicationCleanup,
    *,
    title: str = "Remote Backend Engineer",
) -> UUID:
    job_id = uuid4()
    cleanup.job_ids.append(job_id)

    engine = create_engine(get_settings().database_url)

    with Session(engine) as database:
        database.add(
            Job(
                id=job_id,
                source_name="application-test",
                source_job_id=f"application-{job_id}",
                deduplication_key=sha256(
                    str(job_id).encode(),
                ).hexdigest(),
                source_url=(f"https://jobs.example.com/{job_id}"),
                application_url=(f"https://apply.example.com/{job_id}"),
                title=title,
                company_name="Application Test Company",
                description="Build secure remote applications.",
                requirements="Python and FastAPI",
                location="Remote",
                remote_regions=["Worldwide"],
                employment_type="full_time",
                experience_level="junior",
                salary_min=Decimal("50000"),
                salary_max=Decimal("70000"),
                salary_currency="USD",
                skills=[
                    "Python",
                    "FastAPI",
                ],
                is_remote=True,
                is_active=True,
                published_at=datetime.now(UTC),
            )
        )
        database.commit()

    engine.dispose()

    return job_id


def track_job(
    client: TestClient,
    *,
    job_id: UUID,
    headers: dict[str, str],
    application_status: str = "saved",
    notes: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "job_id": str(job_id),
        "status": application_status,
    }

    if notes is not None:
        payload["notes"] = notes

    response = client.post(
        "/api/v1/applications",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 201

    return response.json()


def test_application_endpoints_require_authentication_and_csrf(
    client: TestClient,
    application_cleanup: ApplicationCleanup,
) -> None:
    unauthenticated_response = client.get(
        "/api/v1/applications",
    )
    assert unauthenticated_response.status_code == 401

    register_and_login(
        client,
        application_cleanup,
    )
    job_id = create_test_job(application_cleanup)

    missing_csrf_response = client.post(
        "/api/v1/applications",
        json={
            "job_id": str(job_id),
            "status": "saved",
        },
    )

    assert missing_csrf_response.status_code == 403


def test_create_get_list_and_reject_duplicate_application(
    client: TestClient,
    application_cleanup: ApplicationCleanup,
) -> None:
    user_id = register_and_login(
        client,
        application_cleanup,
    )
    job_id = create_test_job(application_cleanup)
    headers = csrf_headers(client)

    create_response = client.post(
        "/api/v1/applications",
        headers=headers,
        json={
            "job_id": str(job_id),
            "status": "saved",
            "notes": "  Strong opportunity  ",
        },
    )

    assert create_response.status_code == 201

    response_data = create_response.json()
    application_id = response_data["application"]["id"]

    assert response_data["application"]["user_id"] == (str(user_id))
    assert response_data["application"]["job_id"] == (str(job_id))
    assert response_data["application"]["status"] == "saved"
    assert response_data["application"]["notes"] == ("Strong opportunity")
    assert response_data["application"]["applied_at"] is None
    assert response_data["job"]["id"] == str(job_id)
    assert create_response.headers["cache-control"] == ("private, no-store")

    duplicate_response = client.post(
        "/api/v1/applications",
        headers=headers,
        json={
            "job_id": str(job_id),
        },
    )

    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
        "detail": "This job is already being tracked.",
    }

    list_response = client.get(
        "/api/v1/applications",
    )

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["items"][0] == response_data
    assert list_response.headers["cache-control"] == ("private, no-store")

    detail_response = client.get(
        f"/api/v1/applications/{application_id}",
    )

    assert detail_response.status_code == 200
    assert detail_response.json() == response_data


def test_update_application_status_notes_and_timestamps(
    client: TestClient,
    application_cleanup: ApplicationCleanup,
) -> None:
    register_and_login(
        client,
        application_cleanup,
    )
    job_id = create_test_job(application_cleanup)
    headers = csrf_headers(client)

    created = track_job(
        client,
        job_id=job_id,
        headers=headers,
    )

    application_id = created["application"]["id"]
    initial_status_time = datetime.fromisoformat(
        created["application"]["status_changed_at"],
    )

    applied_response = client.patch(
        f"/api/v1/applications/{application_id}",
        headers=headers,
        json={
            "status": "applied",
            "notes": "Submitted through company website.",
        },
    )

    assert applied_response.status_code == 200

    applied = applied_response.json()["application"]

    assert applied["status"] == "applied"
    assert applied["notes"] == ("Submitted through company website.")
    assert applied["applied_at"] is not None

    applied_status_time = datetime.fromisoformat(
        applied["status_changed_at"],
    )
    assert applied_status_time >= initial_status_time

    interview_response = client.patch(
        f"/api/v1/applications/{application_id}",
        headers=headers,
        json={
            "status": "interview",
            "notes": "   ",
        },
    )

    assert interview_response.status_code == 200

    interview = interview_response.json()["application"]

    assert interview["status"] == "interview"
    assert interview["notes"] is None
    assert interview["applied_at"] == applied["applied_at"]

    saved_response = client.patch(
        f"/api/v1/applications/{application_id}",
        headers=headers,
        json={
            "status": "saved",
        },
    )

    assert saved_response.status_code == 200
    assert saved_response.json()["application"]["status"] == ("saved")
    assert saved_response.json()["application"]["applied_at"] is None


def test_application_list_supports_status_filter_and_pagination(
    client: TestClient,
    application_cleanup: ApplicationCleanup,
) -> None:
    register_and_login(
        client,
        application_cleanup,
    )
    headers = csrf_headers(client)

    saved_job = create_test_job(
        application_cleanup,
        title="Saved Job",
    )
    applied_job = create_test_job(
        application_cleanup,
        title="Applied Job",
    )
    interview_job = create_test_job(
        application_cleanup,
        title="Interview Job",
    )

    track_job(
        client,
        job_id=saved_job,
        headers=headers,
        application_status="saved",
    )
    applied = track_job(
        client,
        job_id=applied_job,
        headers=headers,
        application_status="applied",
    )
    track_job(
        client,
        job_id=interview_job,
        headers=headers,
        application_status="interview",
    )

    filtered_response = client.get(
        "/api/v1/applications",
        params={
            "status": "applied",
        },
    )

    assert filtered_response.status_code == 200
    assert filtered_response.json()["total"] == 1
    assert filtered_response.json()["items"] == [
        applied,
    ]

    paginated_response = client.get(
        "/api/v1/applications",
        params={
            "limit": 2,
            "offset": 1,
        },
    )

    assert paginated_response.status_code == 200
    assert paginated_response.json()["total"] == 3
    assert paginated_response.json()["limit"] == 2
    assert paginated_response.json()["offset"] == 1
    assert len(paginated_response.json()["items"]) == 2


def test_application_validation_rejects_invalid_state(
    client: TestClient,
    application_cleanup: ApplicationCleanup,
) -> None:
    register_and_login(
        client,
        application_cleanup,
    )
    job_id = create_test_job(application_cleanup)
    headers = csrf_headers(client)
    timestamp = datetime.now(UTC).isoformat()

    invalid_create_response = client.post(
        "/api/v1/applications",
        headers=headers,
        json={
            "job_id": str(job_id),
            "status": "saved",
            "applied_at": timestamp,
        },
    )

    assert invalid_create_response.status_code == 422

    created = track_job(
        client,
        job_id=job_id,
        headers=headers,
    )
    application_id = created["application"]["id"]

    invalid_time_response = client.patch(
        f"/api/v1/applications/{application_id}",
        headers=headers,
        json={
            "applied_at": timestamp,
        },
    )

    assert invalid_time_response.status_code == 409
    assert invalid_time_response.json() == {
        "detail": ("A saved job cannot have an applied_at value.")
    }

    empty_update_response = client.patch(
        f"/api/v1/applications/{application_id}",
        headers=headers,
        json={},
    )
    assert empty_update_response.status_code == 422

    null_status_response = client.patch(
        f"/api/v1/applications/{application_id}",
        headers=headers,
        json={
            "status": None,
        },
    )
    assert null_status_response.status_code == 422


def test_applications_are_isolated_between_users(
    client: TestClient,
    application_cleanup: ApplicationCleanup,
) -> None:
    register_and_login(
        client,
        application_cleanup,
    )
    job_id = create_test_job(application_cleanup)
    first_headers = csrf_headers(client)

    created = track_job(
        client,
        job_id=job_id,
        headers=first_headers,
    )
    application_id = created["application"]["id"]

    client.cookies.clear()

    register_and_login(
        client,
        application_cleanup,
    )
    second_headers = csrf_headers(client)

    list_response = client.get(
        "/api/v1/applications",
    )
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 0

    detail_response = client.get(
        f"/api/v1/applications/{application_id}",
    )
    assert detail_response.status_code == 404

    update_response = client.patch(
        f"/api/v1/applications/{application_id}",
        headers=second_headers,
        json={
            "status": "applied",
        },
    )
    assert update_response.status_code == 404

    delete_response = client.delete(
        f"/api/v1/applications/{application_id}",
        headers=second_headers,
    )
    assert delete_response.status_code == 404


def test_delete_application_removes_tracking_record(
    client: TestClient,
    application_cleanup: ApplicationCleanup,
) -> None:
    register_and_login(
        client,
        application_cleanup,
    )
    job_id = create_test_job(application_cleanup)
    headers = csrf_headers(client)

    created = track_job(
        client,
        job_id=job_id,
        headers=headers,
    )
    application_id = created["application"]["id"]

    delete_response = client.delete(
        f"/api/v1/applications/{application_id}",
        headers=headers,
    )

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert delete_response.headers["cache-control"] == ("private, no-store")

    detail_response = client.get(
        f"/api/v1/applications/{application_id}",
    )

    assert detail_response.status_code == 404
