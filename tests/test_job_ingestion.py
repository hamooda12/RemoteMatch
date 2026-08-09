import asyncio
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
from app.models.job_source_reference import JobSourceReference
from app.repositories.job_source_reference import JobSourceReferenceRepository
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


async def get_reference(
    database: AsyncSession,
    record: JobIngestionRecord,
) -> JobSourceReference | None:
    return await JobSourceReferenceRepository(database).get_by_source(
        record.source_name,
        record.source_job_id,
    )


async def count_references_for_job(
    database: AsyncSession,
    job_id,
) -> int:
    total = await database.scalar(
        select(func.count())
        .select_from(JobSourceReference)
        .where(JobSourceReference.job_id == job_id)
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
    record = create_ingestion_record(test_token)

    result = await JobIngestionService(database).ingest(
        record,
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
    assert result.job.first_seen_at is not None
    assert await count_test_jobs(database, test_token) == 1

    reference = await get_reference(database, record)
    assert reference is not None
    assert reference.job_id == result.job.id
    assert reference.source_url == str(record.source_url)
    assert reference.first_seen_at == observed_at
    assert reference.last_seen_at == observed_at
    assert await count_references_for_job(database, result.job.id) == 1


@pytest.mark.anyio
async def test_ingestion_updates_job_from_same_source(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)
    record = create_ingestion_record(test_token)

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
        record,
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
    # skills is an enrichment/list field (_ENRICHMENT_LIST_FIELDS): even a
    # legacy-source repeat merges into the accumulated list rather than
    # replacing it, so "FastAPI" from the first observation survives.
    assert updated_result.job.skills == [
        "Python",
        "FastAPI",
        "Django",
        "PostgreSQL",
        "Docker",
    ]
    assert await count_test_jobs(database, test_token) == 1

    # Same (source_name, source_job_id): still exactly one reference, whose
    # last_seen_at advances but whose first_seen_at never moves.
    reference = await get_reference(database, record)
    assert reference is not None
    assert reference.first_seen_at == first_observation
    assert reference.last_seen_at == second_observation
    assert await count_references_for_job(database, first_result.job.id) == 1


@pytest.mark.anyio
async def test_legacy_source_repeat_preserves_secondary_enrichment(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    """Regression test for the Medium finding from the FR-013 code review:
    a legacy-source repeat with its own sparser values must not erase
    enrichment a secondary source already contributed."""
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    # Source A creates the job with a limited skills list and no requirements.
    primary_record = create_ingestion_record(
        test_token,
        source_suffix="source-one",
        source_job_id="external-one",
        description="Backend role.",
        skills=["Python"],
    )
    primary_result = await service.ingest(primary_record)
    assert primary_result.job.skills == ["Python"]
    assert primary_result.job.requirements is None

    # Source B matches the same logical job (same fingerprint) and enriches it.
    secondary_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="external-two",
        description="Backend role.",
        requirements="Kubernetes experience required.",
        skills=["Docker"],
    )
    secondary_result = await service.ingest(secondary_record)
    assert secondary_result.action == JobIngestionAction.DUPLICATE
    assert {"Python", "Docker"} <= set(secondary_result.job.skills)
    assert secondary_result.job.requirements == "Kubernetes experience required."

    # Source A is observed again with its *original*, sparser values.
    repeated_primary_result = await service.ingest(primary_record)

    assert repeated_primary_result.action == JobIngestionAction.UPDATED
    assert repeated_primary_result.job.id == primary_result.job.id
    # Secondary enrichment must survive Source A's sparser repeat observation.
    assert {"Python", "Docker"} <= set(repeated_primary_result.job.skills)
    assert repeated_primary_result.job.requirements == "Kubernetes experience required."
    assert await count_references_for_job(database, primary_result.job.id) == 2


@pytest.mark.anyio
async def test_legacy_source_repeat_still_updates_core_fields(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    """The enrichment-preservation fix must not turn the legacy branch into
    fully backfill-only behavior -- core/source-owned fields must still
    fully follow the legacy source's latest posting."""
    database, test_token = ingestion_context
    service = JobIngestionService(database)
    record = create_ingestion_record(test_token)

    first_result = await service.ingest(record)
    assert first_result.job.title == "Backend Engineer"
    assert first_result.job.description == "Build remote APIs using Python and FastAPI."

    corrected_record = create_ingestion_record(
        test_token,
        title="Senior Backend Engineer",
        description="Corrected description after a source-side edit.",
    )
    corrected_result = await service.ingest(corrected_record)

    assert corrected_result.action == JobIngestionAction.UPDATED
    assert corrected_result.job.id == first_result.job.id
    assert corrected_result.job.title == "Senior Backend Engineer"
    assert corrected_result.job.description == "Corrected description after a source-side edit."


@pytest.mark.anyio
async def test_legacy_source_can_update_an_already_populated_scalar_enrichment_field(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    """The legacy/authoritative source must be able to extend or change a
    scalar enrichment field's value, not just backfill it once."""
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    base_record = create_ingestion_record(test_token)
    first_expires_at = datetime(2026, 9, 1, tzinfo=UTC)
    second_expires_at = datetime(2026, 10, 1, tzinfo=UTC)

    first_record = JobIngestionRecord(
        **{
            **base_record.model_dump(mode="python"),
            "expires_at": first_expires_at,
        }
    )
    first_result = await service.ingest(first_record)
    assert first_result.job.expires_at == first_expires_at

    second_record = JobIngestionRecord(
        **{
            **base_record.model_dump(mode="python"),
            "expires_at": second_expires_at,
        }
    )
    second_result = await service.ingest(second_record)

    assert second_result.action == JobIngestionAction.UPDATED
    assert second_result.job.id == first_result.job.id
    assert second_result.job.expires_at == second_expires_at


@pytest.mark.anyio
async def test_legacy_source_sending_none_preserves_existing_scalar_enrichment_value(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    """An incoming None from the legacy source must never erase a value
    already set (whether it set that value itself or another source did)."""
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    record_with_url = create_ingestion_record(test_token)
    assert record_with_url.application_url is not None
    first_result = await service.ingest(record_with_url)
    assert first_result.job.application_url == str(record_with_url.application_url)

    record_without_url = JobIngestionRecord(
        **{
            **record_with_url.model_dump(mode="python"),
            "application_url": None,
        }
    )
    second_result = await service.ingest(record_without_url)

    assert second_result.action == JobIngestionAction.UPDATED
    assert second_result.job.id == first_result.job.id
    assert second_result.job.application_url == str(record_with_url.application_url)


@pytest.mark.anyio
async def test_secondary_source_cannot_overwrite_already_populated_scalar_enrichment_value(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    """A secondary source stays backfill-only: it must not override a
    scalar enrichment value the legacy/authoritative source already set,
    even when its own incoming value differs."""
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    primary_record = create_ingestion_record(
        test_token,
        source_suffix="source-one",
        source_job_id="external-one",
    )
    primary_result = await service.ingest(primary_record)
    assert primary_result.job.employment_type == "full_time"

    secondary_base_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="external-two",
    )
    secondary_record = JobIngestionRecord(
        **{
            **secondary_base_record.model_dump(mode="python"),
            "employment_type": "contract",
        }
    )
    secondary_result = await service.ingest(secondary_record)

    assert secondary_result.action == JobIngestionAction.DUPLICATE
    assert secondary_result.job.id == primary_result.job.id
    assert secondary_result.job.employment_type == "full_time"


@pytest.mark.anyio
async def test_collection_enrichment_fields_never_shrink_on_legacy_repeat(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    """skills/remote_regions must keep union-merge semantics -- never
    shrink -- even on a legacy-source repeat with a smaller incoming list."""
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    record = create_ingestion_record(
        test_token,
        description="Backend role.",
        skills=["Python", "Docker"],
    )
    first_result = await service.ingest(record)
    assert {"Python", "Docker"} <= set(first_result.job.skills)

    sparser_record = create_ingestion_record(
        test_token,
        description="Backend role.",
        skills=["Python"],
    )
    second_result = await service.ingest(sparser_record)

    assert second_result.action == JobIngestionAction.UPDATED
    assert second_result.job.id == first_result.job.id
    assert {"Python", "Docker"} <= set(second_result.job.skills)


@pytest.mark.anyio
async def test_ingestion_deduplicates_different_sources(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    first_record = create_ingestion_record(
        test_token,
        source_suffix="source-one",
        source_job_id="external-one",
    )
    first_result = await service.ingest(first_record)

    second_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="external-two",
        description=("The same job with Python, FastAPI, and Docker."),
        requirements="PostgreSQL experience.",
        skills=["Docker"],
    )
    duplicate_result = await service.ingest(second_record)

    assert duplicate_result.action == (JobIngestionAction.DUPLICATE)
    assert duplicate_result.job.id == first_result.job.id
    # Legacy compatibility fields stay on the source that created the Job --
    # the second source's identity is never written there.
    assert duplicate_result.job.source_name.endswith("source-one")
    assert duplicate_result.job.source_job_id == "external-one"
    assert duplicate_result.job.source_url == str(first_record.source_url)
    assert duplicate_result.job.skills == [
        "Python",
        "FastAPI",
        "Docker",
        "PostgreSQL",
    ]
    assert duplicate_result.job.requirements == ("PostgreSQL experience.")
    assert await count_test_jobs(database, test_token) == 1

    # Both sources are retained as independent JobSourceReference rows for
    # the same logical Job (FR-013: retain all source references).
    primary_reference = await get_reference(database, first_record)
    secondary_reference = await get_reference(database, second_record)
    assert primary_reference is not None
    assert secondary_reference is not None
    assert primary_reference.job_id == first_result.job.id
    assert secondary_reference.job_id == first_result.job.id
    assert secondary_reference.source_url == str(second_record.source_url)
    assert await count_references_for_job(database, first_result.job.id) == 2

    # Aggregate Job.last_seen_at advances even though the second observation
    # came from a source that never owned the legacy identity fields.
    assert duplicate_result.job.last_seen_at >= first_result.job.last_seen_at


@pytest.mark.anyio
async def test_repeated_secondary_source_observation_is_idempotent(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    primary_record = create_ingestion_record(
        test_token,
        source_suffix="source-one",
        source_job_id="external-one",
    )
    primary_result = await service.ingest(primary_record)

    secondary_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="external-two",
    )
    first_observation = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    second_observation = first_observation + timedelta(hours=2)

    first_secondary_result = await service.ingest(
        secondary_record,
        observed_at=first_observation,
    )

    # Re-observe the same secondary source with *different* content -- the
    # canonical Job must not flip-flop to this source's values.
    changed_secondary_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="external-two",
        title="A Completely Different Title",
        company_name="A Completely Different Company",
    )
    second_secondary_result = await service.ingest(
        changed_secondary_record,
        observed_at=second_observation,
    )

    assert first_secondary_result.action == JobIngestionAction.DUPLICATE
    assert second_secondary_result.action == JobIngestionAction.UPDATED
    assert second_secondary_result.job.id == primary_result.job.id

    # Canonical fields stay whatever the legacy/primary source provided --
    # never overwritten by the secondary source's re-observation.
    assert second_secondary_result.job.title == primary_result.job.title
    assert second_secondary_result.job.company_name == primary_result.job.company_name
    assert second_secondary_result.job.source_name.endswith("source-one")
    assert second_secondary_result.job.source_job_id == "external-one"

    assert await count_references_for_job(database, primary_result.job.id) == 2
    reference = await get_reference(database, secondary_record)
    assert reference is not None
    assert reference.first_seen_at == first_observation
    assert reference.last_seen_at == second_observation

    # Aggregate freshness still advances from a secondary-only observation.
    assert second_secondary_result.job.last_seen_at == second_observation
    assert second_secondary_result.job.first_seen_at == primary_result.job.first_seen_at


@pytest.mark.anyio
async def test_secondary_reference_source_url_updates_independently_of_legacy_field(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    primary_record = create_ingestion_record(test_token)
    primary_result = await service.ingest(primary_record)
    original_legacy_source_url = primary_result.job.source_url

    secondary_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="job-two",
    )
    await service.ingest(secondary_record)

    moved_secondary_record = JobIngestionRecord(
        **{
            **secondary_record.model_dump(mode="python"),
            "source_url": "https://jobs.example.com/source-two/relocated",
            "application_url": "https://apply.example.com/source-two/relocated",
        }
    )
    result = await service.ingest(moved_secondary_record)

    reference = await get_reference(database, secondary_record)
    assert reference is not None
    assert reference.source_url == str(moved_secondary_record.source_url)

    # The legacy Job.source_url is only ever written by the source that owns
    # it -- a secondary source's URL change must never leak into it.
    assert result.job.source_url == original_legacy_source_url


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
    assert await count_references_for_job(database, first_result.job.id) == 1
    assert await count_references_for_job(database, second_result.job.id) == 1


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

    reference_repository = JobSourceReferenceRepository(database)
    first_reference = await reference_repository.get_by_source(
        first_record.source_name,
        first_record.source_job_id,
    )
    second_reference = await reference_repository.get_by_source(
        second_record.source_name,
        second_record.source_job_id,
    )

    assert first_reference is not None
    assert second_reference is not None
    assert first_reference.job.id == first_result.job.id
    assert second_reference.job.id == second_result.job.id
    assert first_reference.job.title == "Backend Engineer"
    assert second_reference.job.title == "Frontend Engineer"
    assert await count_test_jobs(database, test_token) == 2


@pytest.mark.anyio
async def test_secondary_source_reobserved_with_conflicting_fingerprint_raises(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    primary_record = create_ingestion_record(
        test_token,
        source_suffix="source-one",
        source_job_id="job-one",
    )
    other_job_record = create_ingestion_record(
        test_token,
        source_suffix="source-other",
        source_job_id="job-other",
        title="Totally Different Role",
        company_name="Totally Different Company",
    )
    secondary_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="job-two",
    )

    await service.ingest(primary_record)
    await service.ingest(other_job_record)
    # First observation attaches "source-two" as a secondary reference on
    # the primary job (same fingerprint as primary_record).
    await service.ingest(secondary_record)

    # This source now re-syncs with content whose fingerprint matches the
    # *other* job -- its existing reference points at the wrong Job.
    conflicting_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="job-two",
        title="Totally Different Role",
        company_name="Totally Different Company",
    )

    with pytest.raises(
        JobIngestionConflictError,
        match="conflicts with another canonical job",
    ):
        await service.ingest(conflicting_record)


@pytest.mark.anyio
async def test_duplicate_ingestion_reactivates_job(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    service = JobIngestionService(database)

    first_result = await service.ingest(create_ingestion_record(test_token))

    first_result.job.is_active = False
    await database.commit()

    secondary_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="job-two",
    )
    duplicate_result = await service.ingest(secondary_record)

    assert duplicate_result.action == (JobIngestionAction.DUPLICATE)
    assert duplicate_result.job.id == first_result.job.id
    assert duplicate_result.job.is_active is True
    assert await count_test_jobs(database, test_token) == 1

    reference = await get_reference(database, secondary_record)
    assert reference is not None
    assert reference.job_id == first_result.job.id


@pytest.mark.anyio
async def test_concurrent_first_time_create_recovers_without_conflict(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context
    record = create_ingestion_record(
        test_token,
        source_suffix="source-race",
        source_job_id="job-race",
    )

    engine = create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def ingest_via_new_session():
        async with session_factory() as session:
            return await JobIngestionService(session).ingest(record)

    try:
        results = await asyncio.gather(
            ingest_via_new_session(),
            ingest_via_new_session(),
        )
    finally:
        await engine.dispose()

    assert len({result.job.id for result in results}) == 1
    assert {result.action for result in results} <= {
        JobIngestionAction.CREATED,
        JobIngestionAction.UPDATED,
    }
    assert await count_test_jobs(database, test_token) == 1
    assert await count_references_for_job(database, results[0].job.id) == 1


@pytest.mark.anyio
async def test_concurrent_new_secondary_reference_recovers_without_conflict(
    ingestion_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = ingestion_context

    primary_result = await JobIngestionService(database).ingest(create_ingestion_record(test_token))

    secondary_record = create_ingestion_record(
        test_token,
        source_suffix="source-two",
        source_job_id="job-two",
    )

    engine = create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def ingest_via_new_session():
        async with session_factory() as session:
            return await JobIngestionService(session).ingest(secondary_record)

    try:
        results = await asyncio.gather(
            ingest_via_new_session(),
            ingest_via_new_session(),
        )
    finally:
        await engine.dispose()

    assert {result.job.id for result in results} == {primary_result.job.id}
    assert {result.action for result in results} <= {
        JobIngestionAction.DUPLICATE,
        JobIngestionAction.UPDATED,
    }
    assert await count_references_for_job(database, primary_result.job.id) == 2

    reference_count = await database.scalar(
        select(func.count())
        .select_from(JobSourceReference)
        .where(
            JobSourceReference.source_name == secondary_record.source_name,
            JobSourceReference.source_job_id == secondary_record.source_job_id,
        )
    )
    assert reference_count == 1
