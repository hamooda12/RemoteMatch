from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.models.job import Job
from app.repositories.job import JobRepository
from app.schemas.job_ingestion import JobIngestionRecord
from app.services.job_ingestion import (
    JobIngestionAction,
    JobIngestionConflictError,
    JobIngestionService,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def ingestion_context() -> AsyncIterator[tuple[AsyncSession, str]]:
    test_token = uuid4().hex
    engine = create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as database:
        try:
            yield database, test_token
        finally:
            await database.rollback()
            await database.execute(
                delete(Job).where(Job.source_name.like(f"ingestion-{test_token}%"))
            )
            await database.commit()

    await engine.dispose()


def create_ingestion_record(
    test_token: str,
    *,
    source_suffix: str = "source-one",
    source_job_id: str = "job-one",
    title: str = "Backend Engineer",
    company_name: str = "Acme Remote",
    description: str = ("Build remote APIs using Python and FastAPI."),
    requirements: str | None = None,
    skills: list[str] | None = None,
) -> JobIngestionRecord:
    return JobIngestionRecord(
        source_name=f"ingestion-{test_token}-{source_suffix}",
        source_job_id=source_job_id,
        source_url=(f"https://jobs.example.com/{source_suffix}/{source_job_id}"),
        application_url=(f"https://apply.example.com/{source_suffix}/{source_job_id}"),
        title=title,
        company_name=company_name,
        description=description,
        requirements=requirements,
        location="Remote",
        remote_regions=["Worldwide"],
        employment_type="full_time",
        experience_level="junior",
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        skills=skills or [],
        is_remote=True,
        published_at=datetime(
            2026,
            8,
            3,
            10,
            0,
            tzinfo=UTC,
        ),
    )


async def count_test_jobs(
    database: AsyncSession,
    test_token: str,
) -> int:
    total = await database.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.source_name.like(f"ingestion-{test_token}%"))
    )

    return int(total or 0)


@pytest.mark.anyio
async def test_ingestion_creates_normalized_job(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    observed_at = datetime(
        2026,
        8,
        3,
        12,
        0,
        tzinfo=UTC,
    )

    result = await JobIngestionService(database).ingest(
        create_ingestion_record(test_token),
        observed_at=observed_at,
    )

    assert result.action == JobIngestionAction.CREATED
    assert result.job.source_job_id == "job-one"
    assert result.job.skills == [
        "Python",
        "FastAPI",
    ]
    assert result.job.is_active is True
    assert result.job.last_seen_at == observed_at
    assert await count_test_jobs(database, test_token) == 1


@pytest.mark.anyio
async def test_ingestion_updates_job_from_same_source(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    first_observation = datetime(
        2026,
        8,
        3,
        12,
        0,
        tzinfo=UTC,
    )
    second_observation = first_observation + timedelta(hours=1)

    first_result = await service.ingest(
        create_ingestion_record(test_token),
        observed_at=first_observation,
    )
    first_seen_at = first_result.job.first_seen_at

    updated_record = create_ingestion_record(
        test_token,
        description=("Build APIs with Python, Django, and PostgreSQL."),
        requirements="Docker deployment experience.",
        skills=["Django"],
    )

    updated_result = await service.ingest(
        updated_record,
        observed_at=second_observation,
    )

    assert updated_result.action == JobIngestionAction.UPDATED
    assert updated_result.job.id == first_result.job.id
    assert updated_result.job.first_seen_at == first_seen_at
    assert updated_result.job.last_seen_at == second_observation
    assert updated_result.job.skills == [
        "Django",
        "Python",
        "PostgreSQL",
        "Docker",
    ]
    assert await count_test_jobs(database, test_token) == 1


@pytest.mark.anyio
async def test_ingestion_deduplicates_different_sources(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    first_result = await service.ingest(
        create_ingestion_record(
            test_token,
            source_suffix="source-one",
            source_job_id="external-one",
        )
    )

    duplicate_result = await service.ingest(
        create_ingestion_record(
            test_token,
            source_suffix="source-two",
            source_job_id="external-two",
            description=("The same job with Python, FastAPI, and Docker."),
            requirements="PostgreSQL experience.",
            skills=["Docker"],
        )
    )

    assert duplicate_result.action == (JobIngestionAction.DUPLICATE)
    assert duplicate_result.job.id == first_result.job.id
    assert duplicate_result.job.source_name.endswith("source-one")
    assert duplicate_result.job.source_job_id == "external-one"
    assert duplicate_result.job.skills == [
        "Python",
        "FastAPI",
        "Docker",
        "PostgreSQL",
    ]
    assert duplicate_result.job.requirements == ("PostgreSQL experience.")
    assert await count_test_jobs(database, test_token) == 1


@pytest.mark.anyio
async def test_ingestion_keeps_different_jobs_separate(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    first_result = await service.ingest(create_ingestion_record(test_token))
    second_result = await service.ingest(
        create_ingestion_record(
            test_token,
            source_suffix="source-two",
            source_job_id="job-two",
            company_name="Another Company",
        )
    )

    assert first_result.action == JobIngestionAction.CREATED
    assert second_result.action == JobIngestionAction.CREATED
    assert first_result.job.id != second_result.job.id
    assert await count_test_jobs(database, test_token) == 2


@pytest.mark.anyio
async def test_ingestion_detects_identity_conflict(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    first_record = create_ingestion_record(
        test_token,
        source_suffix="source-one",
        source_job_id="job-one",
        title="Backend Engineer",
        company_name="First Company",
    )
    second_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="job-two",
        title="Frontend Engineer",
        company_name="Second Company",
    )

    first_result = await service.ingest(first_record)
    second_result = await service.ingest(second_record)

    conflicting_record = create_ingestion_record(
        test_token,
        source_suffix="source-one",
        source_job_id="job-one",
        title="Frontend Engineer",
        company_name="Second Company",
    )

    with pytest.raises(
        JobIngestionConflictError,
        match="conflicts with another canonical job",
    ):
        await service.ingest(conflicting_record)

    first_job = await JobRepository(database).get_by_source(
        first_record.source_name,
        first_record.source_job_id,
    )
    second_job = await JobRepository(database).get_by_source(
        second_record.source_name,
        second_record.source_job_id,
    )

    assert first_job is not None
    assert second_job is not None
    assert first_job.id == first_result.job.id
    assert second_job.id == second_result.job.id
    assert first_job.title == "Backend Engineer"
    assert second_job.title == "Frontend Engineer"
    assert await count_test_jobs(database, test_token) == 2


@pytest.mark.anyio
async def test_duplicate_ingestion_reactivates_job(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    first_result = await service.ingest(create_ingestion_record(test_token))

    first_result.job.is_active = False
    await database.commit()

    duplicate_result = await service.ingest(
        create_ingestion_record(
            test_token,
            source_suffix="source-two",
            source_job_id="job-two",
        )
    )

    assert duplicate_result.action == (JobIngestionAction.DUPLICATE)
    assert duplicate_result.job.id == first_result.job.id
    assert duplicate_result.job.is_active is True
    assert await count_test_jobs(database, test_token) == 1
