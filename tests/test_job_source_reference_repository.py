from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.models.job import Job
from app.models.job_source_reference import JobSourceReference
from app.models.job_sync_run import JobSyncRun, JobSyncRunSource
from app.repositories.job_source_reference import JobSourceReferenceRepository
from app.repositories.job_sync_run import JobSyncRunRepository


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def reference_context() -> AsyncIterator[tuple[AsyncSession, str]]:
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
                delete(Job).where(Job.source_name.like(f"job-source-ref-{test_token}%"))
            )
            await database.commit()

    await engine.dispose()


async def create_test_job(
    database: AsyncSession,
    test_token: str,
    *,
    suffix: str = "one",
) -> Job:
    job = Job(
        source_name=f"job-source-ref-{test_token}-{suffix}",
        source_job_id=f"external-{suffix}",
        deduplication_key=uuid4().hex.ljust(64, "0"),
        source_url=f"https://jobs.example.com/{suffix}",
        title="Backend Engineer",
        company_name="Acme Remote",
        description="Build things.",
        remote_regions=[],
        skills=[],
        is_remote=True,
        is_active=True,
    )
    database.add(job)
    await database.flush()
    return job


async def create_test_run_source(
    database: AsyncSession,
    *,
    source_name: str = "arbeitnow",
) -> JobSyncRunSource:
    repository = JobSyncRunRepository(database)
    run = await repository.create_run()
    await database.flush()
    run_source = await repository.create_run_source(run.id, source_name)
    await database.commit()
    return run_source


async def delete_test_run(
    database: AsyncSession,
    run_id,
) -> None:
    await database.execute(delete(JobSyncRun).where(JobSyncRun.id == run_id))
    await database.commit()


@pytest.mark.anyio
async def test_create_persists_reference_with_matching_first_and_last_seen_at(
    reference_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = reference_context
    job = await create_test_job(database, test_token)
    repository = JobSourceReferenceRepository(database)
    observed_at = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    reference = await repository.create(
        job_id=job.id,
        source_name=f"job-source-ref-{test_token}-probe",
        source_job_id="probe-1",
        source_url="https://jobs.example.com/probe-1",
        observed_at=observed_at,
    )
    await database.commit()

    assert reference.job_id == job.id
    assert reference.first_seen_at == observed_at
    assert reference.last_seen_at == observed_at


@pytest.mark.anyio
async def test_get_by_source_returns_none_when_missing(
    reference_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = reference_context
    repository = JobSourceReferenceRepository(database)

    result = await repository.get_by_source(
        f"job-source-ref-{test_token}-missing",
        "missing",
    )

    assert result is None


@pytest.mark.anyio
async def test_get_by_source_eager_loads_job(
    reference_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = reference_context
    job = await create_test_job(database, test_token)
    repository = JobSourceReferenceRepository(database)
    observed_at = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    await repository.create(
        job_id=job.id,
        source_name=f"job-source-ref-{test_token}-eager",
        source_job_id="probe-2",
        source_url="https://jobs.example.com/probe-2",
        observed_at=observed_at,
    )
    await database.commit()

    reference = await repository.get_by_source(
        f"job-source-ref-{test_token}-eager",
        "probe-2",
    )

    assert reference is not None
    assert reference.job.id == job.id
    assert reference.job.title == "Backend Engineer"


@pytest.mark.anyio
async def test_touch_updates_last_seen_at_and_source_url_but_not_first_seen_at(
    reference_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = reference_context
    job = await create_test_job(database, test_token)
    repository = JobSourceReferenceRepository(database)
    first_observation = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    second_observation = first_observation + timedelta(hours=3)

    reference = await repository.create(
        job_id=job.id,
        source_name=f"job-source-ref-{test_token}-touch",
        source_job_id="probe-3",
        source_url="https://jobs.example.com/probe-3",
        observed_at=first_observation,
    )
    await database.commit()

    JobSourceReferenceRepository.touch(
        reference,
        source_url="https://jobs.example.com/probe-3-moved",
        observed_at=second_observation,
    )
    await database.commit()

    assert reference.first_seen_at == first_observation
    assert reference.last_seen_at == second_observation
    assert reference.source_url == "https://jobs.example.com/probe-3-moved"


@pytest.mark.anyio
async def test_source_name_and_source_job_id_uniqueness_enforced_by_database(
    reference_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = reference_context
    first_job = await create_test_job(database, test_token, suffix="one")
    second_job = await create_test_job(database, test_token, suffix="two")
    repository = JobSourceReferenceRepository(database)
    observed_at = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    await repository.create(
        job_id=first_job.id,
        source_name=f"job-source-ref-{test_token}-unique",
        source_job_id="probe-4",
        source_url="https://jobs.example.com/probe-4",
        observed_at=observed_at,
    )
    await database.commit()

    await repository.create(
        job_id=second_job.id,
        source_name=f"job-source-ref-{test_token}-unique",
        source_job_id="probe-4",
        source_url="https://jobs.example.com/probe-4-again",
        observed_at=observed_at,
    )

    with pytest.raises(IntegrityError):
        await database.commit()

    await database.rollback()


@pytest.mark.anyio
async def test_create_with_sync_run_source_id_persists_it(
    reference_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = reference_context
    job = await create_test_job(database, test_token)
    run_source = await create_test_run_source(database)
    repository = JobSourceReferenceRepository(database)
    observed_at = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    reference = await repository.create(
        job_id=job.id,
        source_name=f"job-source-ref-{test_token}-run-correlated",
        source_job_id="probe-run-1",
        source_url="https://jobs.example.com/probe-run-1",
        observed_at=observed_at,
        sync_run_source_id=run_source.id,
    )
    await database.commit()

    assert reference.last_seen_run_source_id == run_source.id

    await delete_test_run(database, run_source.run_id)


@pytest.mark.anyio
async def test_create_without_sync_run_source_id_leaves_it_null(
    reference_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = reference_context
    job = await create_test_job(database, test_token)
    repository = JobSourceReferenceRepository(database)
    observed_at = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    reference = await repository.create(
        job_id=job.id,
        source_name=f"job-source-ref-{test_token}-no-run",
        source_job_id="probe-run-2",
        source_url="https://jobs.example.com/probe-run-2",
        observed_at=observed_at,
    )
    await database.commit()

    assert reference.last_seen_run_source_id is None


@pytest.mark.anyio
async def test_touch_replaces_last_seen_run_source_id_with_the_latest_observation(
    reference_context: tuple[AsyncSession, str],
) -> None:
    """Pointer-replacement semantics: observing via run-source X then Y moves
    the pointer to Y. No historical membership with X is retained anywhere."""
    database, test_token = reference_context
    job = await create_test_job(database, test_token)
    first_run_source = await create_test_run_source(database, source_name="arbeitnow")
    second_run_source = await create_test_run_source(database, source_name="greenhouse")
    repository = JobSourceReferenceRepository(database)
    observed_at = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    reference = await repository.create(
        job_id=job.id,
        source_name=f"job-source-ref-{test_token}-touch-run",
        source_job_id="probe-run-3",
        source_url="https://jobs.example.com/probe-run-3",
        observed_at=observed_at,
        sync_run_source_id=first_run_source.id,
    )
    await database.commit()
    assert reference.last_seen_run_source_id == first_run_source.id

    JobSourceReferenceRepository.touch(
        reference,
        source_url="https://jobs.example.com/probe-run-3",
        observed_at=observed_at + timedelta(hours=1),
        sync_run_source_id=second_run_source.id,
    )
    await database.commit()

    assert reference.last_seen_run_source_id == second_run_source.id

    await delete_test_run(database, first_run_source.run_id)
    await delete_test_run(database, second_run_source.run_id)


@pytest.mark.anyio
async def test_touch_without_sync_run_source_id_leaves_pointer_unchanged(
    reference_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = reference_context
    job = await create_test_job(database, test_token)
    run_source = await create_test_run_source(database)
    repository = JobSourceReferenceRepository(database)
    observed_at = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    reference = await repository.create(
        job_id=job.id,
        source_name=f"job-source-ref-{test_token}-touch-noop",
        source_job_id="probe-run-4",
        source_url="https://jobs.example.com/probe-run-4",
        observed_at=observed_at,
        sync_run_source_id=run_source.id,
    )
    await database.commit()

    JobSourceReferenceRepository.touch(
        reference,
        source_url="https://jobs.example.com/probe-run-4-moved",
        observed_at=observed_at + timedelta(hours=1),
    )
    await database.commit()

    assert reference.last_seen_run_source_id == run_source.id

    await delete_test_run(database, run_source.run_id)


@pytest.mark.anyio
async def test_deleting_run_sets_null_on_reference_without_deleting_it(
    reference_context: tuple[AsyncSession, str],
) -> None:
    database, test_token = reference_context
    job = await create_test_job(database, test_token)
    run_source = await create_test_run_source(database)
    repository = JobSourceReferenceRepository(database)
    observed_at = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    reference = await repository.create(
        job_id=job.id,
        source_name=f"job-source-ref-{test_token}-delete-run",
        source_job_id="probe-run-5",
        source_url="https://jobs.example.com/probe-run-5",
        observed_at=observed_at,
        sync_run_source_id=run_source.id,
    )
    await database.commit()

    reference_id = reference.id
    run_id = run_source.run_id

    await database.execute(delete(JobSyncRun).where(JobSyncRun.id == run_id))
    await database.commit()

    database.expire_all()
    persisted_reference = await database.get(JobSourceReference, reference_id)

    assert persisted_reference is not None
    assert persisted_reference.last_seen_run_source_id is None
    assert persisted_reference.first_seen_at == observed_at
    assert persisted_reference.last_seen_at == observed_at
