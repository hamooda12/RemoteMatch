from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.job_ingestion import JobIngestionRecord
from app.services.job_normalizer import (
    build_job_deduplication_key,
    build_job_values,
    normalize_job_skills,
)


def valid_job_data() -> dict[str, object]:
    published_at = datetime(
        2026,
        8,
        3,
        10,
        0,
        tzinfo=UTC,
    )

    return {
        "source_name": "remote-jobs",
        "source_job_id": "job-123",
        "source_url": "https://jobs.example.com/job-123",
        "application_url": ("https://apply.example.com/job-123"),
        "title": "Python Backend Engineer",
        "company_name": "Acme Remote",
        "description": ("Build secure APIs using Python and FastAPI."),
        "requirements": "PostgreSQL and Docker experience.",
        "location": "Remote",
        "remote_regions": ["Worldwide", "Europe"],
        "employment_type": "full_time",
        "experience_level": "junior",
        "salary_min": Decimal("50000.00"),
        "salary_max": Decimal("70000.00"),
        "salary_currency": "USD",
        "skills": ["Python"],
        "is_remote": True,
        "published_at": published_at,
        "expires_at": published_at + timedelta(days=30),
    }


def test_ingestion_record_normalizes_values() -> None:
    data = valid_job_data()
    data.update(
        {
            "source_name": "  Remote Jobs_API  ",
            "source_job_id": "  external   123  ",
            "title": "  Python   Backend Engineer ",
            "company_name": "  Acme   Remote ",
            "description": (" Build secure APIs. \n\n Work with a remote team. "),
            "requirements": " Python   and PostgreSQL ",
            "location": "  Worldwide   Remote ",
            "remote_regions": [
                " Worldwide ",
                "worldwide",
                "",
                "Europe",
            ],
            "employment_type": "Full-Time",
            "experience_level": "Entry Level",
            "salary_currency": "usd",
            "skills": [
                " python ",
                "PYTHON",
                "",
                "React.js",
            ],
        }
    )

    record = JobIngestionRecord(**data)

    assert record.source_name == "remote-jobs-api"
    assert record.source_job_id == "external 123"
    assert record.title == "Python Backend Engineer"
    assert record.company_name == "Acme Remote"
    assert record.description == ("Build secure APIs.\nWork with a remote team.")
    assert record.requirements == "Python and PostgreSQL"
    assert record.location == "Worldwide Remote"
    assert record.remote_regions == [
        "Worldwide",
        "Europe",
    ]
    assert record.employment_type == "full_time"
    assert record.experience_level == "entry_level"
    assert record.salary_currency == "USD"
    assert record.skills == [
        "python",
        "React.js",
    ]


def test_ingestion_record_rejects_salary_without_currency() -> None:
    data = valid_job_data()
    data["salary_currency"] = None

    with pytest.raises(
        ValidationError,
        match="salary_currency is required",
    ):
        JobIngestionRecord(**data)


def test_ingestion_record_rejects_invalid_salary_range() -> None:
    data = valid_job_data()
    data["salary_min"] = Decimal("80000.00")
    data["salary_max"] = Decimal("70000.00")

    with pytest.raises(
        ValidationError,
        match="salary_min cannot exceed salary_max",
    ):
        JobIngestionRecord(**data)


def test_ingestion_record_rejects_invalid_expiration() -> None:
    data = valid_job_data()
    published_at = data["published_at"]
    assert isinstance(published_at, datetime)

    data["expires_at"] = published_at - timedelta(days=1)

    with pytest.raises(
        ValidationError,
        match="expires_at cannot be earlier",
    ):
        JobIngestionRecord(**data)


def test_ingestion_record_rejects_non_remote_jobs() -> None:
    data = valid_job_data()
    data["is_remote"] = False

    with pytest.raises(ValidationError):
        JobIngestionRecord(**data)


def test_ingestion_record_requires_timezone() -> None:
    data = valid_job_data()
    data["published_at"] = datetime(
        2026,
        8,
        3,
        10,
        0,
    )

    with pytest.raises(
        ValidationError,
        match="must include a timezone",
    ):
        JobIngestionRecord(**data)


def test_ingestion_record_rejects_non_http_url() -> None:
    data = valid_job_data()
    data["source_url"] = "javascript:alert(document.domain)"

    with pytest.raises(ValidationError):
        JobIngestionRecord(**data)


def test_normalizer_canonicalizes_and_merges_skills() -> None:
    data = valid_job_data()
    data.update(
        {
            "skills": [
                "python",
                "React.js",
                "Rust",
                "PYTHON",
            ],
            "description": ("Work with FastAPI, PostgreSQL, and React."),
            "requirements": "Docker experience.",
        }
    )

    record = JobIngestionRecord(**data)

    assert normalize_job_skills(record) == [
        "Python",
        "React",
        "Rust",
        "FastAPI",
        "PostgreSQL",
        "Docker",
    ]


def test_deduplication_key_is_stable_across_sources() -> None:
    first_data = valid_job_data()
    second_data = valid_job_data()

    second_data.update(
        {
            "source_name": "another-source",
            "source_job_id": "different-id",
            "source_url": ("https://another.example.com/different-id"),
            "application_url": None,
            "title": "  PYTHON backend engineer ",
            "company_name": "ACME REMOTE",
            "location": "remote",
            "remote_regions": [
                "europe",
                "WORLDWIDE",
            ],
            "description": "A differently written description.",
        }
    )

    first_record = JobIngestionRecord(**first_data)
    second_record = JobIngestionRecord(**second_data)

    assert build_job_deduplication_key(first_record) == build_job_deduplication_key(second_record)


def test_deduplication_key_changes_for_different_job() -> None:
    first_data = valid_job_data()
    second_data = valid_job_data()
    second_data["company_name"] = "Different Company"

    first_record = JobIngestionRecord(**first_data)
    second_record = JobIngestionRecord(**second_data)

    assert build_job_deduplication_key(first_record) != build_job_deduplication_key(second_record)


def test_build_job_values_creates_database_values() -> None:
    observed_at = datetime(
        2026,
        8,
        3,
        12,
        0,
        tzinfo=UTC,
    )
    record = JobIngestionRecord(**valid_job_data())

    values = build_job_values(
        record,
        observed_at=observed_at,
    )

    assert values["source_name"] == "remote-jobs"
    assert values["source_job_id"] == "job-123"
    assert values["source_url"] == ("https://jobs.example.com/job-123")
    assert values["application_url"] == ("https://apply.example.com/job-123")
    assert values["salary_currency"] == "USD"
    assert values["skills"] == [
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Docker",
    ]
    assert values["is_remote"] is True
    assert values["is_active"] is True
    assert values["last_seen_at"] == observed_at

    deduplication_key = values["deduplication_key"]

    assert isinstance(deduplication_key, str)
    assert len(deduplication_key) == 64
