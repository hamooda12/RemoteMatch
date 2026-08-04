from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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

JOB_TEST_PASSWORD = "j" * 16


def register_and_login(
    client: TestClient,
    email: str,
) -> None:
    registration_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "Job Test User",
            "password": JOB_TEST_PASSWORD,
        },
    )
    assert registration_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": JOB_TEST_PASSWORD,
        },
    )
    assert login_response.status_code == 200


def create_deduplication_key(value: str) -> str:
    return sha256(value.encode()).hexdigest()


@pytest.fixture(autouse=True)
def clear_job_test_cookies(
    client: TestClient,
) -> Iterator[None]:
    client.cookies.clear()
    yield
    client.cookies.clear()


@pytest.fixture
def job_context(
    client: TestClient,
) -> Iterator[dict[str, UUID]]:
    email = f"jobs-{uuid4()}@example.com"
    engine = create_engine(get_settings().database_url)

    python_job_id = uuid4()
    frontend_job_id = uuid4()
    inactive_job_id = uuid4()

    marker_id = uuid4()
    marker = marker_id.hex

    job_ids = [
        python_job_id,
        frontend_job_id,
        inactive_job_id,
    ]

    try:
        register_and_login(client, email)

        current_time = datetime.now(UTC)

        jobs = [
            Job(
                id=python_job_id,
                source_name="test-source",
                source_job_id=f"python-{uuid4()}",
                deduplication_key=(create_deduplication_key(str(python_job_id))),
                source_url=(f"https://jobs.example.com/{python_job_id}"),
                application_url=(f"https://apply.example.com/{python_job_id}"),
                title="Python Backend Engineer",
                company_name=f"Acme Remote {marker}",
                description=("Build secure remote APIs using Python and FastAPI."),
                requirements=("Python, FastAPI, and PostgreSQL"),
                location="Remote",
                remote_regions=["Worldwide"],
                employment_type="full_time",
                experience_level="junior",
                salary_min=Decimal("50000.00"),
                salary_max=Decimal("70000.00"),
                salary_currency="USD",
                skills=[
                    "Python",
                    "FastAPI",
                    "PostgreSQL",
                ],
                is_remote=True,
                is_active=True,
                published_at=(current_time - timedelta(hours=1)),
            ),
            Job(
                id=frontend_job_id,
                source_name="test-source",
                source_job_id=f"frontend-{uuid4()}",
                deduplication_key=(create_deduplication_key(str(frontend_job_id))),
                source_url=(f"https://jobs.example.com/{frontend_job_id}"),
                application_url=None,
                title="Frontend Developer",
                company_name=(f"Bright Interfaces {marker}"),
                description=("Create accessible interfaces with React."),
                requirements="React and TypeScript",
                location="Europe",
                remote_regions=["Europe"],
                employment_type="contract",
                experience_level="mid_level",
                salary_min=Decimal("60000.00"),
                salary_max=Decimal("80000.00"),
                salary_currency="EUR",
                skills=[
                    "React",
                    "TypeScript",
                ],
                is_remote=True,
                is_active=True,
                published_at=(current_time - timedelta(hours=2)),
            ),
            Job(
                id=inactive_job_id,
                source_name="test-source",
                source_job_id=f"inactive-{uuid4()}",
                deduplication_key=(create_deduplication_key(str(inactive_job_id))),
                source_url=(f"https://jobs.example.com/{inactive_job_id}"),
                application_url=None,
                title="Inactive Python Job",
                company_name=f"Closed Company {marker}",
                description=("This job is no longer active."),
                requirements=None,
                location="Remote",
                remote_regions=["Worldwide"],
                employment_type="full_time",
                experience_level="junior",
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                skills=["Python"],
                is_remote=True,
                is_active=False,
                published_at=current_time,
            ),
        ]

        with Session(engine) as database:
            database.add_all(jobs)
            database.commit()

        yield {
            "python": python_job_id,
            "frontend": frontend_job_id,
            "inactive": inactive_job_id,
            "marker": marker_id,
        }
    finally:
        client.cookies.clear()

        with Session(engine) as database:
            database.execute(delete(Job).where(Job.id.in_(job_ids)))
            database.execute(delete(User).where(User.email == email))
            database.commit()

        engine.dispose()


def test_job_endpoints_require_authentication(
    client: TestClient,
) -> None:
    list_response = client.get("/api/v1/jobs")
    detail_response = client.get(f"/api/v1/jobs/{uuid4()}")

    assert list_response.status_code == 401
    assert detail_response.status_code == 401


def test_list_jobs_hides_inactive_jobs(
    client: TestClient,
    job_context: dict[str, UUID],
) -> None:
    response = client.get(
        "/api/v1/jobs",
        params={
            "search": job_context["marker"].hex,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["limit"] == 20
    assert response.json()["offset"] == 0

    items = response.json()["items"]

    assert [item["id"] for item in items] == [
        str(job_context["python"]),
        str(job_context["frontend"]),
    ]
    assert "description" not in items[0]
    assert str(job_context["inactive"]) not in {item["id"] for item in items}
    assert response.headers["cache-control"] == ("private, max-age=60")


def test_get_job_returns_details_and_hides_inactive_job(
    client: TestClient,
    job_context: dict[str, UUID],
) -> None:
    active_response = client.get(f"/api/v1/jobs/{job_context['python']}")

    assert active_response.status_code == 200
    assert active_response.json()["title"] == ("Python Backend Engineer")
    assert active_response.json()["description"] == (
        "Build secure remote APIs using Python and FastAPI."
    )
    assert active_response.json()["requirements"] == ("Python, FastAPI, and PostgreSQL")
    assert active_response.json()["skills"] == [
        "Python",
        "FastAPI",
        "PostgreSQL",
    ]

    inactive_response = client.get(f"/api/v1/jobs/{job_context['inactive']}")
    missing_response = client.get(f"/api/v1/jobs/{uuid4()}")

    assert inactive_response.status_code == 404
    assert missing_response.status_code == 404
    assert inactive_response.json() == {
        "detail": "Job not found.",
    }


def test_job_search_and_filters(
    client: TestClient,
    job_context: dict[str, UUID],
) -> None:
    marker = job_context["marker"].hex

    search_response = client.get(
        "/api/v1/jobs",
        params={
            "search": marker,
        },
    )

    assert search_response.status_code == 200
    assert search_response.json()["total"] == 2

    skills_response = client.get(
        "/api/v1/jobs",
        params={
            "search": marker,
            "skills": "React",
        },
    )

    assert skills_response.status_code == 200
    assert skills_response.json()["total"] == 1
    assert skills_response.json()["items"][0]["id"] == str(job_context["frontend"])

    region_response = client.get(
        "/api/v1/jobs",
        params={
            "search": marker,
            "remote_regions": "Worldwide",
        },
    )

    assert region_response.status_code == 200
    assert region_response.json()["total"] == 1
    assert region_response.json()["items"][0]["id"] == str(job_context["python"])

    experience_response = client.get(
        "/api/v1/jobs",
        params={
            "search": marker,
            "employment_type": "full_time",
            "experience_level": "junior",
        },
    )

    assert experience_response.status_code == 200
    assert experience_response.json()["total"] == 1
    assert experience_response.json()["items"][0]["id"] == str(job_context["python"])


def test_job_salary_filter_requires_currency(
    client: TestClient,
    job_context: dict[str, UUID],
) -> None:
    marker = job_context["marker"].hex

    missing_currency_response = client.get(
        "/api/v1/jobs",
        params={
            "search": marker,
            "minimum_salary": "65000",
        },
    )

    assert missing_currency_response.status_code == 422
    assert missing_currency_response.json() == {
        "detail": ("salary_currency is required when minimum_salary is provided."),
    }

    salary_response = client.get(
        "/api/v1/jobs",
        params={
            "search": marker,
            "minimum_salary": "65000",
            "salary_currency": "usd",
        },
    )

    assert salary_response.status_code == 200
    assert salary_response.json()["total"] == 1
    assert salary_response.json()["items"][0]["id"] == str(job_context["python"])


def test_job_pagination_preserves_total_count(
    client: TestClient,
    job_context: dict[str, UUID],
) -> None:
    response = client.get(
        "/api/v1/jobs",
        params={
            "search": job_context["marker"].hex,
            "limit": 1,
            "offset": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["limit"] == 1
    assert response.json()["offset"] == 1
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["id"] == str(job_context["frontend"])
