from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.integrations.job_sources import (
    JobSourceError,
    JobSourceFetchResult,
    build_job_source_registry,
)
from app.models.job import Job
from app.models.job_sync_run import JobSyncRun
from app.repositories.job import JobRepository
from app.repositories.job_sync_run import JobSyncRunRepository
from app.schemas.job_ingestion import JobIngestionRecord
from app.services.job_normalizer import build_job_values
from app.services.job_sync import (
    JobSyncError,
    JobSyncService,
)


class FakeSourceError(JobSourceError):
    """Raised by a fake job source during tests."""


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


def make_success_source(
    name: str,
    *,
    max_pages: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        max_pages=max_pages,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(
                records=(),
                page=1,
                has_next_page=False,
            )
        ),
    )


def make_failing_source(
    name: str,
    *,
    max_pages: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        max_pages=max_pages,
        fetch_page=AsyncMock(side_effect=FakeSourceError("boom")),
    )


def spy_repository(
    database: AsyncSession,
) -> tuple[JobSyncRunRepository, list[JobSyncRun]]:
    """A real JobSyncRunRepository, with create_run wrapped to record what it created.

    Used only so tests know which run row to inspect afterward -- every
    persistence call still goes through the real repository against the
    real database.
    """
    repository = JobSyncRunRepository(database)
    created_runs: list[JobSyncRun] = []
    original_create_run = repository.create_run

    async def create_run_spy() -> JobSyncRun:
        run = await original_create_run()
        created_runs.append(run)
        return run

    repository.create_run = create_run_spy

    return repository, created_runs


@pytest.mark.anyio
async def test_sync_source_persists_run_and_source_on_success(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)
    source = make_success_source("arbeitnow")

    service = JobSyncService(
        database,
        sources={"arbeitnow": source},
        runs=repository,
    )

    summary = await service.sync_source("arbeitnow", max_pages=1)
    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)

    assert persisted_run is not None
    assert persisted_run.status == "succeeded"
    assert persisted_run.completed_at is not None

    assert len(persisted_run.sources) == 1
    persisted_source = persisted_run.sources[0]
    assert persisted_source.source_name == "arbeitnow"
    assert persisted_source.status == "succeeded"
    assert persisted_source.completed_at is not None
    assert persisted_source.pages_fetched == summary.pages_fetched
    assert persisted_source.fetched_records == summary.fetched_records
    assert persisted_source.error_code is None
    assert persisted_source.error_message is None


@pytest.mark.anyio
async def test_sync_source_persists_run_and_source_on_failure(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)
    source = make_failing_source("greenhouse")

    service = JobSyncService(
        database,
        sources={"greenhouse": source},
        runs=repository,
    )

    with pytest.raises(JobSyncError):
        await service.sync_source("greenhouse", max_pages=1)

    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)

    assert persisted_run is not None
    assert persisted_run.status == "failed"
    assert persisted_run.completed_at is not None

    assert len(persisted_run.sources) == 1
    persisted_source = persisted_run.sources[0]
    assert persisted_source.status == "failed"
    assert persisted_source.completed_at is not None
    assert persisted_source.error_code == "SOURCE_SYNC_FAILED"
    assert persisted_source.error_message is not None
    assert "greenhouse" in persisted_source.error_message


@pytest.mark.anyio
async def test_sync_all_creates_exactly_one_run_for_multiple_sources(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    sources = {
        "himalayas": make_success_source("himalayas"),
        "jobicy": make_success_source("jobicy"),
        "remoteok": make_success_source("remoteok"),
    }

    service = JobSyncService(
        database,
        sources=sources,
        runs=repository,
    )

    summaries = await service.sync_all(max_pages=1)

    assert len(created_runs) == 1
    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)

    assert persisted_run is not None
    assert len(persisted_run.sources) == 3
    assert {source.run_id for source in persisted_run.sources} == {created_runs[0].id}
    assert {source.source_name for source in persisted_run.sources} == set(sources)
    assert len(summaries) == 3


@pytest.mark.anyio
async def test_sync_all_overall_status_succeeded_when_all_sources_succeed(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    sources = {
        "arbeitnow": make_success_source("arbeitnow"),
        "greenhouse": make_success_source("greenhouse"),
    }

    service = JobSyncService(
        database,
        sources=sources,
        runs=repository,
    )

    await service.sync_all(max_pages=1)
    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)

    assert persisted_run is not None
    assert persisted_run.status == "succeeded"
    assert persisted_run.completed_at is not None


@pytest.mark.anyio
async def test_sync_all_overall_status_partial_when_mixed(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    sources = {
        "arbeitnow": make_success_source("arbeitnow"),
        "greenhouse": make_failing_source("greenhouse"),
    }

    service = JobSyncService(
        database,
        sources=sources,
        runs=repository,
    )

    await service.sync_all(max_pages=1)
    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)

    assert persisted_run is not None
    assert persisted_run.status == "partial"


@pytest.mark.anyio
async def test_sync_all_overall_status_failed_when_all_sources_fail(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    sources = {
        "arbeitnow": make_failing_source("arbeitnow"),
        "greenhouse": make_failing_source("greenhouse"),
    }

    service = JobSyncService(
        database,
        sources=sources,
        runs=repository,
    )

    await service.sync_all(max_pages=1)
    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)

    assert persisted_run is not None
    assert persisted_run.status == "failed"


@pytest.mark.anyio
async def test_sync_all_continues_persisting_remaining_sources_after_one_fails(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    first = make_success_source("first")
    second = make_failing_source("second")
    third = make_success_source("third")

    service = JobSyncService(
        database,
        sources={
            "first": first,
            "second": second,
            "third": third,
        },
        runs=repository,
    )

    summaries = await service.sync_all(max_pages=1)
    created_run_ids.append(created_runs[0].id)

    third.fetch_page.assert_awaited_once_with(page=1)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)

    assert persisted_run is not None
    assert persisted_run.status == "partial"

    sources_by_name = {source.source_name: source for source in persisted_run.sources}

    assert sources_by_name["first"].status == "succeeded"
    assert sources_by_name["second"].status == "failed"
    assert sources_by_name["second"].error_code == "SOURCE_SYNC_FAILED"
    assert sources_by_name["third"].status == "succeeded"

    assert len(summaries) == 3


@pytest.mark.anyio
async def test_sync_all_continues_after_ingestion_rollback_recovery(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real ingestion rollback expires `run` mid-loop; sync_all() must survive it."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    # Occupies the deduplication_key the "colliding" record below will also produce.
    phantom_record = JobIngestionRecord(
        source_name="phantom-source",
        source_job_id="phantom-job",
        source_url="https://jobs.example.com/phantom",
        title="Race Condition Engineer",
        company_name="Race Co",
        description="Existing job used to force a dedup collision.",
        location="Remote",
        remote_regions=["Worldwide"],
        published_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
    )
    phantom_values = build_job_values(phantom_record, observed_at=datetime.now(UTC))
    job_repository = JobRepository(database)
    phantom_job = await job_repository.create(phantom_values)
    await database.commit()

    # Same dedup fingerprint as phantom_record, different source_job_id.
    colliding_record = JobIngestionRecord(
        source_name="colliding-source",
        source_job_id="colliding-job",
        source_url="https://jobs.example.com/colliding",
        title="Race Condition Engineer",
        company_name="Race Co",
        description="Triggers the dedup collision.",
        location="Remote",
        remote_regions=["Worldwide"],
        published_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
    )

    colliding_source = SimpleNamespace(
        name="colliding",
        max_pages=1,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(
                records=(colliding_record,),
                page=1,
                has_next_page=False,
            )
        ),
    )
    after_source = make_success_source("after")

    # Forces the first dedup check to miss the already-committed phantom job,
    # simulating the TOCTOU window a real concurrent insert would create.
    original_get_by_deduplication_key = JobRepository.get_by_deduplication_key
    call_count = 0

    async def flaky_get_by_deduplication_key(
        self: JobRepository,
        deduplication_key: str,
    ) -> Job | None:
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return None

        return await original_get_by_deduplication_key(self, deduplication_key)

    monkeypatch.setattr(
        JobRepository,
        "get_by_deduplication_key",
        flaky_get_by_deduplication_key,
    )

    service = JobSyncService(
        database,
        sources={
            "colliding": colliding_source,
            "after": after_source,
        },
        runs=repository,
    )

    summaries = await service.sync_all(max_pages=1)
    created_run_ids.append(created_runs[0].id)

    # Confirms the real rollback-recovery path actually ran (forced miss, then real recheck).
    assert call_count == 2

    # Fails with MissingGreenlet before the fix.
    after_source.fetch_page.assert_awaited_once_with(page=1)

    assert [summary.source_name for summary in summaries] == [
        "colliding",
        "after",
    ]
    assert summaries[0].error is None
    assert summaries[0].duplicates == 1
    assert summaries[1].error is None

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)

    # Terminal status, not stuck at "running".
    assert persisted_run is not None
    assert persisted_run.status == "succeeded"
    assert persisted_run.completed_at is not None

    sources_by_name = {source.source_name: source for source in persisted_run.sources}
    assert set(sources_by_name) == {"colliding", "after"}
    assert sources_by_name["colliding"].status == "succeeded"
    assert sources_by_name["after"].status == "succeeded"

    await database.execute(delete(Job).where(Job.id == phantom_job.id))
    await database.commit()


@pytest.mark.anyio
async def test_sync_all_skips_disabled_sources_end_to_end(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled connector must be absent from the registry, unattempted,
    and unpersisted -- proving the config flag propagates through
    build_job_source_registry() into a real sync_all() run."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    settings = get_settings().model_copy(
        update={"job_source_jobicy_enabled": False},
    )
    registry = build_job_source_registry(settings)

    assert "jobicy" not in registry

    for source in registry.values():
        monkeypatch.setattr(
            source,
            "fetch_page",
            AsyncMock(
                return_value=JobSourceFetchResult(
                    records=(),
                    page=1,
                    has_next_page=False,
                )
            ),
        )

    service = JobSyncService(
        database,
        sources=registry,
        runs=repository,
    )

    summaries = await service.sync_all(max_pages=1)
    created_run_ids.append(created_runs[0].id)

    assert "jobicy" not in {summary.source_name for summary in summaries}
    assert {summary.source_name for summary in summaries} == {
        "arbeitnow",
        "greenhouse",
        "himalayas",
        "remoteok",
    }

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)

    assert persisted_run is not None
    assert persisted_run.status == "succeeded"
    assert "jobicy" not in {source.source_name for source in persisted_run.sources}
    assert {source.source_name for source in persisted_run.sources} == {
        "arbeitnow",
        "greenhouse",
        "himalayas",
        "remoteok",
    }


@pytest.mark.anyio
async def test_sync_all_raises_before_creating_run_when_every_source_disabled(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, _created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    settings = get_settings().model_copy(
        update={
            "job_source_arbeitnow_enabled": False,
            "job_source_greenhouse_enabled": False,
            "job_source_himalayas_enabled": False,
            "job_source_jobicy_enabled": False,
            "job_source_remoteok_enabled": False,
        },
    )
    registry = build_job_source_registry(settings)

    assert registry == {}

    service = JobSyncService(
        database,
        sources=registry,
        runs=repository,
    )

    with pytest.raises(ValueError, match="No job sources are enabled."):
        await service.sync_all(max_pages=1)

    assert created_runs == []
