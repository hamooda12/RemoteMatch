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
from app.models.cv_document import CVDocument
from app.models.job import Job
from app.models.profile import Profile
from app.models.user import User
from app.services.cv_skill_extractor import (
    SKILL_EXTRACTION_VERSION,
)

MATCHING_TEST_PASSWORD = "m" * 16


@dataclass
class CleanupRecords:
    emails: list[str] = field(default_factory=list)
    job_ids: list[UUID] = field(default_factory=list)


@pytest.fixture(autouse=True)
def clear_matching_cookies(
    client: TestClient,
) -> Iterator[None]:
    client.cookies.clear()
    yield
    client.cookies.clear()


@pytest.fixture
def cleanup_records(
    client: TestClient,
) -> Iterator[CleanupRecords]:
    records = CleanupRecords()
    yield records

    client.cookies.clear()

    engine = create_engine(get_settings().database_url)

    with Session(engine) as database:
        if records.job_ids:
            database.execute(
                delete(Job).where(
                    Job.id.in_(records.job_ids),
                )
            )

        if records.emails:
            database.execute(
                delete(User).where(
                    User.email.in_(records.emails),
                )
            )

        database.commit()

    engine.dispose()


def register_and_login(
    client: TestClient,
    records: CleanupRecords,
) -> UUID:
    email = f"matching-{uuid4()}@example.com"
    records.emails.append(email)

    registration_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": "Matching User",
            "password": MATCHING_TEST_PASSWORD,
        },
    )

    assert registration_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": MATCHING_TEST_PASSWORD,
        },
    )

    assert login_response.status_code == 200

    return UUID(registration_response.json()["id"])


def create_candidate_data(
    *,
    user_id: UUID,
    skills: tuple[str, ...],
    target_roles: tuple[str, ...] = (),
    experience_level: str | None = None,
    minimum_salary: Decimal | None = None,
    salary_currency: str | None = None,
    excluded_technologies: tuple[str, ...] = (),
    processed: bool = True,
) -> None:
    engine = create_engine(get_settings().database_url)
    file_data = b"%PDF-1.4 matching test"

    with Session(engine) as database:
        database.add(
            Profile(
                user_id=user_id,
                timezone="Asia/Hebron",
                target_roles=list(target_roles),
                experience_level=experience_level,
                minimum_salary=minimum_salary,
                salary_currency=salary_currency,
                excluded_technologies=list(
                    excluded_technologies,
                ),
                availability={},
            )
        )

        database.add(
            CVDocument(
                user_id=user_id,
                original_filename="matching-resume.pdf",
                media_type="application/pdf",
                size_bytes=len(file_data),
                content_sha256=sha256(file_data).hexdigest(),
                file_data=file_data,
                parse_status=("processed" if processed else "pending"),
                extracted_text=(" ".join(skills) if processed else None),
                extracted_skills=(list(skills) if processed else []),
                skills_extraction_version=(SKILL_EXTRACTION_VERSION if processed else None),
            )
        )

        database.commit()

    engine.dispose()


def create_job(
    records: CleanupRecords,
    *,
    title: str = "Senior Backend Engineer",
    skills: tuple[str, ...] = (
        "Python",
        "FastAPI",
        "PostgreSQL",
    ),
    experience_level: str | None = "junior",
    salary_min: Decimal | None = Decimal("50000"),
    salary_max: Decimal | None = Decimal("70000"),
    salary_currency: str | None = "USD",
) -> UUID:
    job_id = uuid4()
    records.job_ids.append(job_id)

    engine = create_engine(get_settings().database_url)

    with Session(engine) as database:
        database.add(
            Job(
                id=job_id,
                source_name="matching-test",
                source_job_id=f"matching-{job_id}",
                deduplication_key=sha256(
                    str(job_id).encode(),
                ).hexdigest(),
                source_url=(f"https://jobs.example.com/{job_id}"),
                application_url=(f"https://apply.example.com/{job_id}"),
                title=title,
                company_name="Matching Test Company",
                description=("Build secure remote services."),
                requirements=", ".join(skills) or None,
                location="Remote",
                remote_regions=["Worldwide"],
                employment_type="full_time",
                experience_level=experience_level,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_currency=salary_currency,
                skills=list(skills),
                is_remote=True,
                is_active=True,
                published_at=datetime.now(UTC),
            )
        )

        database.commit()

    engine.dispose()

    return job_id


def test_job_match_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get(
        f"/api/v1/jobs/{uuid4()}/match",
    )

    assert response.status_code == 401


def test_job_match_requires_completed_profile(
    client: TestClient,
    cleanup_records: CleanupRecords,
) -> None:
    register_and_login(
        client,
        cleanup_records,
    )
    job_id = create_job(cleanup_records)

    response = client.get(
        f"/api/v1/jobs/{job_id}/match",
    )

    assert response.status_code == 409
    assert response.json() == {"detail": ("Complete your profile before requesting job matches.")}


def test_job_match_requires_processed_cv(
    client: TestClient,
    cleanup_records: CleanupRecords,
) -> None:
    user_id = register_and_login(
        client,
        cleanup_records,
    )

    create_candidate_data(
        user_id=user_id,
        skills=(),
        target_roles=("Backend Engineer",),
        processed=False,
    )

    job_id = create_job(cleanup_records)

    response = client.get(
        f"/api/v1/jobs/{job_id}/match",
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": ("Upload and process your CV before requesting job matches.")
    }


def test_job_match_returns_complete_score_breakdown(
    client: TestClient,
    cleanup_records: CleanupRecords,
) -> None:
    user_id = register_and_login(
        client,
        cleanup_records,
    )

    create_candidate_data(
        user_id=user_id,
        skills=(
            "Python",
            "FastAPI",
            "PostgreSQL",
        ),
        target_roles=("Backend Engineer",),
        experience_level="mid_level",
        minimum_salary=Decimal("60000"),
        salary_currency="USD",
    )

    job_id = create_job(cleanup_records)

    response = client.get(
        f"/api/v1/jobs/{job_id}/match",
    )

    assert response.status_code == 200

    response_data = response.json()

    assert response_data["job"]["id"] == str(job_id)
    assert response_data["score"] == 100
    assert response_data["is_eligible"] is True
    assert response_data["breakdown"] == {
        "skill_score": 60,
        "role_score": 20,
        "experience_score": 10,
        "salary_score": 10,
    }
    assert response_data["matched_skills"] == [
        "Python",
        "FastAPI",
        "PostgreSQL",
    ]
    assert response_data["missing_skills"] == []
    assert response_data["excluded_skills"] == []
    assert response_data["reasons"]
    assert response.headers["cache-control"] == ("private, max-age=60")


def test_job_match_uses_only_current_users_profile_and_cv(
    client: TestClient,
    cleanup_records: CleanupRecords,
) -> None:
    first_user_id = register_and_login(
        client,
        cleanup_records,
    )

    create_candidate_data(
        user_id=first_user_id,
        skills=(
            "Python",
            "FastAPI",
            "PostgreSQL",
        ),
        target_roles=("Backend Engineer",),
        experience_level="mid_level",
        minimum_salary=Decimal("60000"),
        salary_currency="USD",
    )

    job_id = create_job(cleanup_records)

    first_response = client.get(
        f"/api/v1/jobs/{job_id}/match",
    )

    assert first_response.status_code == 200
    assert first_response.json()["score"] == 100

    client.cookies.clear()

    second_user_id = register_and_login(
        client,
        cleanup_records,
    )

    create_candidate_data(
        user_id=second_user_id,
        skills=("React",),
        target_roles=("Frontend Developer",),
    )

    second_response = client.get(
        f"/api/v1/jobs/{job_id}/match",
    )

    assert second_response.status_code == 200
    assert second_response.json()["score"] == 10
    assert second_response.json()["matched_skills"] == []
    assert second_response.json()["missing_skills"] == [
        "Python",
        "FastAPI",
        "PostgreSQL",
    ]


def test_excluded_technology_returns_ineligible_match(
    client: TestClient,
    cleanup_records: CleanupRecords,
) -> None:
    user_id = register_and_login(
        client,
        cleanup_records,
    )

    create_candidate_data(
        user_id=user_id,
        skills=("Python",),
        target_roles=("Backend Engineer",),
        excluded_technologies=("Docker",),
    )

    job_id = create_job(
        cleanup_records,
        skills=(
            "Python",
            "Docker",
        ),
    )

    response = client.get(
        f"/api/v1/jobs/{job_id}/match",
    )

    assert response.status_code == 200
    assert response.json()["score"] == 0
    assert response.json()["is_eligible"] is False
    assert response.json()["excluded_skills"] == [
        "Docker",
    ]


def test_ranked_job_matches_are_sorted_filtered_and_paginated(
    client: TestClient,
    cleanup_records: CleanupRecords,
) -> None:
    user_id = register_and_login(
        client,
        cleanup_records,
    )

    marker = uuid4().hex
    unique_skill = f"TestSkill-{marker}"
    target_role = f"Quantum {marker} Engineer"

    create_candidate_data(
        user_id=user_id,
        skills=(unique_skill,),
        target_roles=(target_role,),
        experience_level="junior",
        minimum_salary=Decimal("60000"),
        salary_currency="USD",
    )

    perfect_job_id = create_job(
        cleanup_records,
        title=target_role,
        skills=(unique_skill,),
        experience_level="junior",
    )

    medium_job_id = create_job(
        cleanup_records,
        title=target_role,
        skills=(unique_skill,),
        experience_level="senior",
    )

    lower_job_id = create_job(
        cleanup_records,
        title="Unrelated Position",
        skills=(unique_skill,),
        experience_level="junior",
    )

    first_page_response = client.get(
        "/api/v1/jobs/matches",
        params={
            "minimum_score": 80,
            "limit": 2,
            "offset": 0,
        },
    )

    assert first_page_response.status_code == 200

    first_page = first_page_response.json()

    assert first_page["total"] == 3
    assert first_page["minimum_score"] == 80
    assert first_page["limit"] == 2
    assert first_page["offset"] == 0

    assert [item["job"]["id"] for item in first_page["items"]] == [
        str(perfect_job_id),
        str(medium_job_id),
    ]

    assert [item["score"] for item in first_page["items"]] == [
        100,
        90,
    ]

    second_page_response = client.get(
        "/api/v1/jobs/matches",
        params={
            "minimum_score": 80,
            "limit": 2,
            "offset": 2,
        },
    )

    assert second_page_response.status_code == 200

    second_page = second_page_response.json()

    assert second_page["total"] == 3
    assert len(second_page["items"]) == 1
    assert second_page["items"][0]["job"]["id"] == (str(lower_job_id))
    assert second_page["items"][0]["score"] == 80

    filtered_response = client.get(
        "/api/v1/jobs/matches",
        params={
            "minimum_score": 95,
        },
    )

    assert filtered_response.status_code == 200
    assert filtered_response.json()["total"] == 1
    assert filtered_response.json()["items"][0]["job"]["id"] == (str(perfect_job_id))
    assert filtered_response.headers["cache-control"] == ("private, max-age=60")


def test_ranked_matches_exclude_ineligible_jobs(
    client: TestClient,
    cleanup_records: CleanupRecords,
) -> None:
    user_id = register_and_login(
        client,
        cleanup_records,
    )

    marker = uuid4().hex
    unique_skill = f"EligibleSkill-{marker}"
    target_role = f"Platform {marker} Engineer"

    create_candidate_data(
        user_id=user_id,
        skills=(unique_skill,),
        target_roles=(target_role,),
        experience_level="junior",
        minimum_salary=Decimal("60000"),
        salary_currency="USD",
        excluded_technologies=("Docker",),
    )

    eligible_job_id = create_job(
        cleanup_records,
        title=target_role,
        skills=(unique_skill,),
    )

    excluded_job_id = create_job(
        cleanup_records,
        title=target_role,
        skills=(
            unique_skill,
            "Docker",
        ),
    )

    response = client.get(
        "/api/v1/jobs/matches",
        params={
            "minimum_score": 80,
        },
    )

    assert response.status_code == 200

    response_data = response.json()
    returned_ids = {item["job"]["id"] for item in response_data["items"]}

    assert response_data["total"] == 1
    assert str(eligible_job_id) in returned_ids
    assert str(excluded_job_id) not in returned_ids


def test_ranked_matches_require_authentication(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/jobs/matches",
    )

    assert response.status_code == 401
