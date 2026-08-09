from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.models.job_sync_run import JobSyncRun, JobSyncRunSource
from app.repositories.job_sync_run import JobSyncRunRepository


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def job_sync_run_context() -> AsyncIterator[tuple[AsyncSession, list[UUID]]]:
    engine = create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    created_run_ids: list[UUID] = []

    async with session_factory() as database:
        try:
            yield database, created_run_ids
        finally:
            await database.rollback()
            if created_run_ids:
                await database.execute(delete(JobSyncRun).where(JobSyncRun.id.in_(created_run_ids)))
                await database.commit()

    await engine.dispose()


@pytest.mark.anyio
async def test_create_run_persists_running_status_and_start_time(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository = JobSyncRunRepository(database)

    run = await repository.create_run()
    await database.flush()
    created_run_ids.append(run.id)

    assert run.status == "running"
    assert run.started_at is not None
    assert run.completed_at is None


@pytest.mark.anyio
async def test_create_run_source_persists_and_links_to_run(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository = JobSyncRunRepository(database)

    run = await repository.create_run()
    await database.flush()
    created_run_ids.append(run.id)

    source = await repository.create_run_source(run.id, "arbeitnow")
    await database.flush()

    assert source.run_id == run.id
    assert source.source_name == "arbeitnow"
    assert source.status == "running"
    assert source.pages_fetched == 0
    assert source.fetched_records == 0
    assert source.error_code is None
    assert source.error_message is None


@pytest.mark.anyio
async def test_complete_run_source_updates_status_counts_and_completed_at(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository = JobSyncRunRepository(database)

    run = await repository.create_run()
    await database.flush()
    created_run_ids.append(run.id)

    source = await repository.create_run_source(run.id, "greenhouse")
    await database.flush()

    completed_at = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    JobSyncRunRepository.complete_run_source(
        source,
        status="succeeded",
        completed_at=completed_at,
        pages_fetched=1,
        fetched_records=10,
        created=8,
        updated=2,
    )
    await database.commit()
    await database.refresh(source)

    assert source.status == "succeeded"
    assert source.completed_at == completed_at
    assert source.pages_fetched == 1
    assert source.fetched_records == 10
    assert source.created == 8
    assert source.updated == 2
    assert source.duplicates == 0


@pytest.mark.anyio
async def test_complete_run_source_records_error_code_and_message(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository = JobSyncRunRepository(database)

    run = await repository.create_run()
    await database.flush()
    created_run_ids.append(run.id)

    source = await repository.create_run_source(run.id, "jobicy")
    await database.flush()

    completed_at = datetime(2026, 8, 9, 12, 5, tzinfo=UTC)
    JobSyncRunRepository.complete_run_source(
        source,
        status="failed",
        completed_at=completed_at,
        error_code="TRANSPORT_ERROR",
        error_message="Unable to fetch jobs from Jobicy.",
    )
    await database.commit()
    await database.refresh(source)

    assert source.status == "failed"
    assert source.error_code == "TRANSPORT_ERROR"
    assert source.error_message == "Unable to fetch jobs from Jobicy."


@pytest.mark.anyio
async def test_complete_run_updates_overall_status_and_completed_at(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository = JobSyncRunRepository(database)

    run = await repository.create_run()
    await database.flush()
    created_run_ids.append(run.id)

    completed_at = datetime(2026, 8, 9, 12, 10, tzinfo=UTC)
    JobSyncRunRepository.complete_run(
        run,
        status="partial",
        completed_at=completed_at,
    )
    await database.commit()
    await database.refresh(run)

    assert run.status == "partial"
    assert run.completed_at == completed_at


@pytest.mark.anyio
async def test_unique_constraint_rejects_duplicate_source_within_run(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository = JobSyncRunRepository(database)

    run = await repository.create_run()
    await database.flush()
    created_run_ids.append(run.id)

    await repository.create_run_source(run.id, "remoteok")
    await database.flush()

    await repository.create_run_source(run.id, "remoteok")

    with pytest.raises(IntegrityError):
        await database.flush()

    await database.rollback()


@pytest.mark.anyio
async def test_get_run_with_sources_returns_run_and_its_sources(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository = JobSyncRunRepository(database)

    run = await repository.create_run()
    await database.flush()
    created_run_ids.append(run.id)

    await repository.create_run_source(run.id, "himalayas")
    await repository.create_run_source(run.id, "remoteok")
    await database.commit()

    fetched_run = await repository.get_run_with_sources(run.id)

    assert fetched_run is not None
    assert fetched_run.id == run.id
    assert {source.source_name for source in fetched_run.sources} == {
        "himalayas",
        "remoteok",
    }


@pytest.mark.anyio
async def test_delete_run_cascades_to_remove_sources_when_collection_unloaded(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository = JobSyncRunRepository(database)

    run = await repository.create_run()
    await database.flush()
    created_run_ids.append(run.id)

    source = await repository.create_run_source(run.id, "arbeitnow")
    await database.commit()

    source_id = source.id
    run_id = run.id

    database.expire_all()

    fresh_run = await database.get(JobSyncRun, run_id)
    assert fresh_run is not None
    assert "sources" in inspect(fresh_run).unloaded

    await repository.delete_run(fresh_run)
    await database.commit()

    assert await database.get(JobSyncRunSource, source_id) is None
    assert await database.get(JobSyncRun, run_id) is None


@pytest.mark.anyio
async def test_delete_run_cascades_to_remove_sources_when_collection_loaded(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository = JobSyncRunRepository(database)

    run = await repository.create_run()
    await database.flush()
    created_run_ids.append(run.id)

    source = await repository.create_run_source(run.id, "greenhouse")
    await database.commit()

    source_id = source.id
    run_id = run.id

    loaded_run = await repository.get_run_with_sources(run_id)
    assert loaded_run is not None
    assert "sources" not in inspect(loaded_run).unloaded
    assert len(loaded_run.sources) == 1

    await repository.delete_run(loaded_run)
    await database.commit()

    assert await database.get(JobSyncRunSource, source_id) is None
    assert await database.get(JobSyncRun, run_id) is None
