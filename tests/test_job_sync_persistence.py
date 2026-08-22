import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.db.advisory_lock import SOURCE_SYNC_LOCK_NAMESPACE
from app.integrations.job_sources import (
    JobSourceError,
    JobSourceFetchResult,
    build_job_source_registry,
)
from app.models.job import Job
from app.models.job_sync_run import JobSyncRun
from app.repositories.job import JobRepository
from app.repositories.job_source_reference import JobSourceReferenceRepository
from app.repositories.job_sync_run import JobSyncRunRepository
from app.schemas.job_ingestion import JobIngestionRecord
from app.services.job_ingestion import JobIngestionAction, JobIngestionService
from app.services.job_normalizer import build_job_values
from app.services.job_sync import (
    JobSourceSyncAlreadyRunningError,
    JobSourceSyncLockLostError,
    JobSyncError,
    JobSyncService,
    JobSyncSummary,
    always_acquired_source_lock,
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


@asynccontextmanager
async def isolated_job_sync_database() -> AsyncIterator[tuple[AsyncEngine, AsyncSession]]:
    """A dedicated engine+session pair sharing the same physical database as
    job_sync_run_context, used to simulate a fully separate process/
    connection for cross-connection advisory-lock proofs."""
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
            yield engine, database
        finally:
            await database.rollback()

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


def make_test_ingestion_record(
    test_token: str,
    *,
    source_name: str,
    source_job_id: str,
) -> JobIngestionRecord:
    return JobIngestionRecord(
        source_name=f"job-sync-persist-{test_token}-{source_name}",
        source_job_id=source_job_id,
        source_url=f"https://jobs.example.com/{source_name}/{source_job_id}",
        title="Backend Engineer",
        company_name="Acme Remote",
        description="Build remote things.",
        location="Remote",
        remote_regions=["Worldwide"],
        published_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
    )


def make_record_source(
    name: str,
    records: tuple[JobIngestionRecord, ...],
    *,
    max_pages: int = 1,
    has_next_page: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        max_pages=max_pages,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(
                records=records,
                page=1,
                has_next_page=has_next_page,
            )
        ),
    )


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
    assert persisted_source.page_limit == 1
    assert persisted_source.pagination_exhausted is True


@pytest.mark.anyio
async def test_sync_source_natural_pagination_completion_persists_exhausted_true(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """A source whose final fetched page reports has_next_page=False -- the
    loop reached natural completion within the page budget it was given."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    source = SimpleNamespace(
        name="himalayas",
        max_pages=5,
        fetch_page=AsyncMock(
            side_effect=[
                JobSourceFetchResult(records=(), page=1, has_next_page=True),
                JobSourceFetchResult(records=(), page=2, has_next_page=False),
            ]
        ),
    )

    service = JobSyncService(
        database,
        sources={"himalayas": source},
        runs=repository,
    )

    await service.sync_source("himalayas", max_pages=2)
    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)
    assert persisted_run is not None

    persisted_source = persisted_run.sources[0]
    assert persisted_source.page_limit == 2
    assert persisted_source.pagination_exhausted is True
    assert persisted_source.pages_fetched == 2


@pytest.mark.anyio
async def test_sync_source_page_limit_truncation_persists_exhausted_false(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """A source that still reports has_next_page=True when the run's
    page_limit is reached -- the loop was truncated, not naturally
    completed. This must NOT be recorded the same as a true completion."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    source = SimpleNamespace(
        name="arbeitnow",
        max_pages=5,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(records=(), page=1, has_next_page=True)
        ),
    )

    service = JobSyncService(
        database,
        sources={"arbeitnow": source},
        runs=repository,
    )

    await service.sync_source("arbeitnow", max_pages=1)
    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)
    assert persisted_run is not None

    persisted_source = persisted_run.sources[0]
    assert persisted_source.page_limit == 1
    assert persisted_source.pagination_exhausted is False
    assert persisted_source.pages_fetched == 1


@pytest.mark.anyio
async def test_sync_all_effective_page_limit_is_min_of_requested_and_source_max(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """sync_all()'s effective page_limit is min(requested max_pages, the
    source's own max_pages) -- not the raw requested value in isolation."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    source = make_success_source("jobicy", max_pages=1)

    service = JobSyncService(
        database,
        sources={"jobicy": source},
        runs=repository,
    )

    await service.sync_all(max_pages=5)
    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)
    assert persisted_run is not None

    persisted_source = persisted_run.sources[0]
    assert persisted_source.page_limit == 1


@pytest.mark.anyio
async def test_sync_source_single_page_success_is_exhausted(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """Greenhouse/RemoteOK/Jobicy-style connectors report has_next_page=False
    on their only call -- this is technically "exhausted", but is not by
    itself proof the fetched set is the source's complete inventory."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)
    source = make_success_source("greenhouse", max_pages=1)

    service = JobSyncService(
        database,
        sources={"greenhouse": source},
        runs=repository,
    )

    await service.sync_source("greenhouse", max_pages=1)
    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)
    assert persisted_run is not None

    persisted_source = persisted_run.sources[0]
    assert persisted_source.pagination_exhausted is True


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
    assert persisted_source.pages_fetched == 0
    assert persisted_source.page_limit == 1
    assert persisted_source.pagination_exhausted is False


@pytest.mark.anyio
async def test_sync_source_persists_partial_progress_when_later_page_fails(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """page 1 succeeds (20 records: 5 created, 10 updated, 5 duplicate),
    page 2's fetch fails. The run-source row must record page 1's real
    accumulated progress, not zeroed-out counts, and must NOT claim
    pagination_exhausted -- natural completion was never reached."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    page_one_records = tuple(object() for _ in range(20))
    source = SimpleNamespace(
        name="arbeitnow",
        max_pages=5,
        fetch_page=AsyncMock(
            side_effect=[
                JobSourceFetchResult(records=page_one_records, page=1, has_next_page=True),
                FakeSourceError("boom"),
            ]
        ),
    )

    service = JobSyncService(
        database,
        sources={"arbeitnow": source},
        runs=repository,
        # This test verifies summary/counting and persistence bookkeeping
        # with a mocked ingest() -- not real ingestion -- so the real
        # pinned-connection lock (which would otherwise construct its own
        # JobIngestionService and ignore this monkeypatch) is bypassed.
        source_lock=always_acquired_source_lock,
    )
    service.ingestion.ingest = AsyncMock(
        side_effect=(
            [SimpleNamespace(action=JobIngestionAction.CREATED) for _ in range(5)]
            + [SimpleNamespace(action=JobIngestionAction.UPDATED) for _ in range(10)]
            + [SimpleNamespace(action=JobIngestionAction.DUPLICATE) for _ in range(5)]
        )
    )

    with pytest.raises(JobSyncError):
        await service.sync_source("arbeitnow", max_pages=2)

    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)
    assert persisted_run is not None
    assert persisted_run.status == "failed"

    persisted_source = persisted_run.sources[0]
    assert persisted_source.status == "failed"
    assert persisted_source.error_code == "SOURCE_SYNC_FAILED"
    assert persisted_source.pages_fetched == 1
    assert persisted_source.fetched_records == 20
    assert persisted_source.created == 5
    assert persisted_source.updated == 10
    assert persisted_source.duplicates == 5
    assert persisted_source.conflicts == 0
    assert persisted_source.rejected == 0
    assert persisted_source.skipped_non_remote == 0
    assert persisted_source.page_limit == 2
    assert persisted_source.pagination_exhausted is False


@pytest.mark.anyio
async def test_sync_source_correlates_references_to_its_run_source(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)
    test_token = uuid4().hex

    records = (
        make_test_ingestion_record(test_token, source_name="arbeitnow", source_job_id="one"),
        make_test_ingestion_record(test_token, source_name="arbeitnow", source_job_id="two"),
    )
    source = make_record_source("arbeitnow", records)

    service = JobSyncService(
        database,
        sources={"arbeitnow": source},
        runs=repository,
    )

    try:
        await service.sync_source("arbeitnow", max_pages=1)
        created_run_ids.append(created_runs[0].id)

        persisted_run = await repository.get_run_with_sources(created_runs[0].id)
        assert persisted_run is not None
        run_source_id = persisted_run.sources[0].id

        reference_repository = JobSourceReferenceRepository(database)
        for record in records:
            reference = await reference_repository.get_by_source(
                record.source_name,
                record.source_job_id,
            )
            assert reference is not None
            assert reference.last_seen_run_source_id == run_source_id
    finally:
        await database.execute(
            delete(Job).where(Job.source_name.like(f"job-sync-persist-{test_token}%"))
        )
        await database.commit()


@pytest.mark.anyio
async def test_sync_all_correlates_each_source_to_its_own_run_source(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """References observed by different sources within the same run must
    each point at their own JobSyncRunSource, not the other source's."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)
    test_token = uuid4().hex

    first_record = make_test_ingestion_record(
        test_token,
        source_name="arbeitnow",
        source_job_id="one",
    )
    second_record = make_test_ingestion_record(
        test_token,
        source_name="greenhouse",
        source_job_id="one",
    )

    first_source = make_record_source("arbeitnow", (first_record,))
    second_source = make_record_source("greenhouse", (second_record,))

    service = JobSyncService(
        database,
        sources={
            "arbeitnow": first_source,
            "greenhouse": second_source,
        },
        runs=repository,
    )

    try:
        await service.sync_all(max_pages=1)
        created_run_ids.append(created_runs[0].id)

        persisted_run = await repository.get_run_with_sources(created_runs[0].id)
        assert persisted_run is not None
        run_sources_by_name = {source.source_name: source for source in persisted_run.sources}

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
        assert first_reference.last_seen_run_source_id == run_sources_by_name["arbeitnow"].id
        assert second_reference.last_seen_run_source_id == run_sources_by_name["greenhouse"].id
        assert first_reference.last_seen_run_source_id != second_reference.last_seen_run_source_id
    finally:
        await database.execute(
            delete(Job).where(Job.source_name.like(f"job-sync-persist-{test_token}%"))
        )
        await database.commit()


@pytest.mark.anyio
async def test_sync_source_partial_failure_retains_correlation_from_completed_pages(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """page 1 succeeds and its references are committed with real ingestion
    before page 2 fails. Even though the run-source ends up status="failed",
    the correlation recorded for page 1's references must remain intact --
    no reconciliation/rollback of already-committed correlations happens."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)
    test_token = uuid4().hex

    page_one_records = (
        make_test_ingestion_record(test_token, source_name="arbeitnow", source_job_id="one"),
        make_test_ingestion_record(test_token, source_name="arbeitnow", source_job_id="two"),
    )
    source = SimpleNamespace(
        name="arbeitnow",
        max_pages=5,
        fetch_page=AsyncMock(
            side_effect=[
                JobSourceFetchResult(records=page_one_records, page=1, has_next_page=True),
                FakeSourceError("boom"),
            ]
        ),
    )

    service = JobSyncService(
        database,
        sources={"arbeitnow": source},
        runs=repository,
    )

    try:
        with pytest.raises(JobSyncError):
            await service.sync_source("arbeitnow", max_pages=2)

        created_run_ids.append(created_runs[0].id)

        persisted_run = await repository.get_run_with_sources(created_runs[0].id)
        assert persisted_run is not None
        persisted_source = persisted_run.sources[0]
        assert persisted_source.status == "failed"

        reference_repository = JobSourceReferenceRepository(database)
        for record in page_one_records:
            reference = await reference_repository.get_by_source(
                record.source_name,
                record.source_job_id,
            )
            assert reference is not None
            assert reference.last_seen_run_source_id == persisted_source.id
    finally:
        await database.execute(
            delete(Job).where(Job.source_name.like(f"job-sync-persist-{test_token}%"))
        )
        await database.commit()


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

    # Registered connector names (not fictional ones): the production
    # advisory-lock module only serves the five known RemoteMatch
    # connectors, and this test exercises the real (non-injected) lock
    # path, so its source names must be real registry names.
    first = make_success_source("arbeitnow")
    second = make_failing_source("greenhouse")
    third = make_success_source("himalayas")

    service = JobSyncService(
        database,
        sources={
            "arbeitnow": first,
            "greenhouse": second,
            "himalayas": third,
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

    assert sources_by_name["arbeitnow"].status == "succeeded"
    assert sources_by_name["arbeitnow"].pagination_exhausted is True
    assert sources_by_name["greenhouse"].status == "failed"
    assert sources_by_name["greenhouse"].error_code == "SOURCE_SYNC_FAILED"
    assert sources_by_name["greenhouse"].page_limit == 1
    assert sources_by_name["greenhouse"].pagination_exhausted is False
    assert sources_by_name["himalayas"].status == "succeeded"
    assert sources_by_name["himalayas"].pagination_exhausted is True

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

    # Registered connector names: this test exercises the real
    # (non-injected) advisory-lock path via sync_all(), which only serves
    # the five known RemoteMatch connectors.
    colliding_source = SimpleNamespace(
        name="arbeitnow",
        max_pages=1,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(
                records=(colliding_record,),
                page=1,
                has_next_page=False,
            )
        ),
    )
    after_source = make_success_source("greenhouse")

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
            "arbeitnow": colliding_source,
            "greenhouse": after_source,
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
        "arbeitnow",
        "greenhouse",
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
    assert set(sources_by_name) == {"arbeitnow", "greenhouse"}
    assert sources_by_name["arbeitnow"].status == "succeeded"
    assert sources_by_name["greenhouse"].status == "succeeded"

    # The reference recovered via the rollback-recovery path must still end
    # up correlated to the run-source that actually observed it.
    reference_repository = JobSourceReferenceRepository(database)
    colliding_reference = await reference_repository.get_by_source(
        colliding_record.source_name,
        colliding_record.source_job_id,
    )
    assert colliding_reference is not None
    assert colliding_reference.last_seen_run_source_id == sources_by_name["arbeitnow"].id

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


@pytest.mark.anyio
async def test_historical_run_source_without_pagination_metadata_reads_as_none(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """Rows created before page_limit/pagination_exhausted existed (or by
    any caller that omits them) must read back as NULL/None -- "unknown" --
    never as a misleading False."""
    database, created_run_ids = job_sync_run_context
    repository = JobSyncRunRepository(database)

    run = await repository.create_run()
    await database.flush()
    created_run_ids.append(run.id)

    source = await repository.create_run_source(run.id, "arbeitnow")
    await database.flush()

    JobSyncRunRepository.complete_run_source(
        source,
        status="succeeded",
        completed_at=datetime.now(UTC),
        pages_fetched=1,
        fetched_records=0,
    )
    await database.commit()

    persisted_run = await repository.get_run_with_sources(run.id)
    assert persisted_run is not None

    persisted_source = persisted_run.sources[0]
    assert persisted_source.page_limit is None
    assert persisted_source.pagination_exhausted is None


# --- Task B3: same-source overlapping-run safety (real Postgres) --------


@pytest.mark.anyio
async def test_overlapping_same_source_syncs_are_mutually_exclusive(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """Task A holds the arbeitnow lock (blocked mid-fetch); a concurrent
    Task B attempting the same source must fail fast with zero
    fetches/ingestion and a persisted failed audit row, while A completes
    normally once released -- and A's completion is the only write to the
    reference's last_seen_run_source_id, proving B could never have
    overwritten it (Task B2 protection)."""
    database_a, created_run_ids = job_sync_run_context
    repository_a, created_runs_a = spy_repository(database_a)
    test_token = uuid4().hex

    a_is_locked = asyncio.Event()
    release_a = asyncio.Event()

    record = make_test_ingestion_record(
        test_token,
        source_name="arbeitnow",
        source_job_id="one",
    )

    async def blocking_fetch_page(*, page: int) -> JobSourceFetchResult:
        a_is_locked.set()
        await release_a.wait()
        return JobSourceFetchResult(records=(record,), page=page, has_next_page=False)

    source_a = SimpleNamespace(
        name="arbeitnow",
        max_pages=1,
        fetch_page=AsyncMock(side_effect=blocking_fetch_page),
    )
    service_a = JobSyncService(
        database_a,
        sources={"arbeitnow": source_a},
        runs=repository_a,
    )

    task_a = asyncio.create_task(service_a.sync_source("arbeitnow", max_pages=1))
    summary_a: JobSyncSummary | None = None

    try:
        await asyncio.wait_for(a_is_locked.wait(), timeout=5)

        async with isolated_job_sync_database() as (_engine_b, database_b):
            repository_b, created_runs_b = spy_repository(database_b)
            source_b = SimpleNamespace(
                name="arbeitnow",
                max_pages=1,
                fetch_page=AsyncMock(
                    return_value=JobSourceFetchResult(records=(), page=1, has_next_page=False)
                ),
            )
            service_b = JobSyncService(
                database_b,
                sources={"arbeitnow": source_b},
                runs=repository_b,
            )

            with pytest.raises(JobSourceSyncAlreadyRunningError):
                await service_b.sync_source("arbeitnow", max_pages=1)

            source_b.fetch_page.assert_not_awaited()

            persisted_run_b = await repository_b.get_run_with_sources(created_runs_b[0].id)
            assert persisted_run_b is not None
            assert persisted_run_b.status == "failed"
            assert len(persisted_run_b.sources) == 1
            persisted_source_b = persisted_run_b.sources[0]
            assert persisted_source_b.status == "failed"
            assert persisted_source_b.error_code == "SOURCE_SYNC_ALREADY_RUNNING"
            assert persisted_source_b.pages_fetched == 0
            assert persisted_source_b.fetched_records == 0
            assert persisted_source_b.created == 0
            assert persisted_source_b.pagination_exhausted is False

            await database_b.execute(
                delete(JobSyncRun).where(JobSyncRun.id == created_runs_b[0].id)
            )
            await database_b.commit()
    finally:
        release_a.set()
        summary_a = await task_a
        created_run_ids.append(created_runs_a[0].id)

    assert summary_a is not None
    assert summary_a.pages_fetched == 1
    assert summary_a.created == 1

    reference_repository = JobSourceReferenceRepository(database_a)
    try:
        reference = await reference_repository.get_by_source(
            record.source_name,
            record.source_job_id,
        )
        assert reference is not None

        persisted_run_a = await repository_a.get_run_with_sources(created_runs_a[0].id)
        assert persisted_run_a is not None
        assert reference.last_seen_run_source_id == persisted_run_a.sources[0].id
    finally:
        await database_a.execute(
            delete(Job).where(Job.source_name.like(f"job-sync-persist-{test_token}%"))
        )
        await database_a.commit()


@pytest.mark.anyio
async def test_different_source_syncs_are_not_serialized_by_the_lock(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """While Arbeitnow's lock is held, an independent Jobicy sync must
    proceed unaffected -- the lock is per-source, not global."""
    database_a, created_run_ids = job_sync_run_context
    repository_a, created_runs_a = spy_repository(database_a)

    a_is_locked = asyncio.Event()
    release_a = asyncio.Event()

    async def blocking_fetch_page(*, page: int) -> JobSourceFetchResult:
        a_is_locked.set()
        await release_a.wait()
        return JobSourceFetchResult(records=(), page=page, has_next_page=False)

    source_a = SimpleNamespace(
        name="arbeitnow",
        max_pages=1,
        fetch_page=AsyncMock(side_effect=blocking_fetch_page),
    )
    service_a = JobSyncService(
        database_a,
        sources={"arbeitnow": source_a},
        runs=repository_a,
    )

    task_a = asyncio.create_task(service_a.sync_source("arbeitnow", max_pages=1))
    summary_a: JobSyncSummary | None = None

    try:
        await asyncio.wait_for(a_is_locked.wait(), timeout=5)

        async with isolated_job_sync_database() as (_engine_c, database_c):
            repository_c, created_runs_c = spy_repository(database_c)
            source_c = make_success_source("jobicy")
            service_c = JobSyncService(
                database_c,
                sources={"jobicy": source_c},
                runs=repository_c,
            )

            summary_c = await service_c.sync_source("jobicy", max_pages=1)

            assert summary_c.error is None
            source_c.fetch_page.assert_awaited_once_with(page=1)

            persisted_run_c = await repository_c.get_run_with_sources(created_runs_c[0].id)
            assert persisted_run_c is not None
            assert persisted_run_c.status == "succeeded"

            await database_c.execute(
                delete(JobSyncRun).where(JobSyncRun.id == created_runs_c[0].id)
            )
            await database_c.commit()
    finally:
        release_a.set()
        summary_a = await task_a
        created_run_ids.append(created_runs_a[0].id)

    assert summary_a is not None
    assert summary_a.pages_fetched == 1


@pytest.mark.anyio
async def test_source_lock_is_released_after_normal_completion_and_reacquirable(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    first_source = make_success_source("arbeitnow")
    service_one = JobSyncService(
        database,
        sources={"arbeitnow": first_source},
        runs=repository,
    )
    await service_one.sync_source("arbeitnow", max_pages=1)
    created_run_ids.append(created_runs[0].id)

    second_source = make_success_source("arbeitnow")
    service_two = JobSyncService(
        database,
        sources={"arbeitnow": second_source},
        runs=repository,
    )
    summary_two = await service_two.sync_source("arbeitnow", max_pages=1)
    created_run_ids.append(created_runs[1].id)

    assert summary_two.error is None
    second_source.fetch_page.assert_awaited_once_with(page=1)


@pytest.mark.anyio
async def test_source_lock_is_released_after_exception_and_reacquirable(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    """A source fetch failure must release the lock (via the dedicated
    lock connection's transaction rollback), not leak it."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)

    failing_source = make_failing_source("arbeitnow")
    service_one = JobSyncService(
        database,
        sources={"arbeitnow": failing_source},
        runs=repository,
    )
    with pytest.raises(JobSyncError):
        await service_one.sync_source("arbeitnow", max_pages=1)
    created_run_ids.append(created_runs[0].id)

    succeeding_source = make_success_source("arbeitnow")
    service_two = JobSyncService(
        database,
        sources={"arbeitnow": succeeding_source},
        runs=repository,
    )
    summary_two = await service_two.sync_source("arbeitnow", max_pages=1)
    created_run_ids.append(created_runs[1].id)

    assert summary_two.error is None
    succeeding_source.fetch_page.assert_awaited_once_with(page=1)


@pytest.mark.anyio
async def test_sync_all_skips_locked_source_and_continues_with_others(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
) -> None:
    database_a, created_run_ids = job_sync_run_context
    repository_a, created_runs_a = spy_repository(database_a)

    a_is_locked = asyncio.Event()
    release_a = asyncio.Event()

    async def blocking_fetch_page(*, page: int) -> JobSourceFetchResult:
        a_is_locked.set()
        await release_a.wait()
        return JobSourceFetchResult(records=(), page=page, has_next_page=False)

    source_a = SimpleNamespace(
        name="arbeitnow",
        max_pages=1,
        fetch_page=AsyncMock(side_effect=blocking_fetch_page),
    )
    service_a = JobSyncService(
        database_a,
        sources={"arbeitnow": source_a},
        runs=repository_a,
    )

    task_a = asyncio.create_task(service_a.sync_source("arbeitnow", max_pages=1))

    try:
        await asyncio.wait_for(a_is_locked.wait(), timeout=5)

        async with isolated_job_sync_database() as (_engine_b, database_b):
            repository_b, created_runs_b = spy_repository(database_b)
            source_arbeitnow = SimpleNamespace(
                name="arbeitnow",
                max_pages=1,
                fetch_page=AsyncMock(
                    return_value=JobSourceFetchResult(records=(), page=1, has_next_page=False)
                ),
            )
            source_greenhouse = make_success_source("greenhouse")

            service_b = JobSyncService(
                database_b,
                sources={
                    "arbeitnow": source_arbeitnow,
                    "greenhouse": source_greenhouse,
                },
                runs=repository_b,
            )

            summaries = await service_b.sync_all(max_pages=1)

            source_arbeitnow.fetch_page.assert_not_awaited()
            source_greenhouse.fetch_page.assert_awaited_once_with(page=1)

            summaries_by_name = {summary.source_name: summary for summary in summaries}
            assert summaries_by_name["arbeitnow"].error is not None
            assert summaries_by_name["greenhouse"].error is None

            persisted_run_b = await repository_b.get_run_with_sources(created_runs_b[0].id)
            assert persisted_run_b is not None
            assert persisted_run_b.status == "partial"

            sources_by_name = {source.source_name: source for source in persisted_run_b.sources}
            assert sources_by_name["arbeitnow"].status == "failed"
            assert sources_by_name["arbeitnow"].error_code == "SOURCE_SYNC_ALREADY_RUNNING"
            assert sources_by_name["arbeitnow"].pages_fetched == 0
            assert sources_by_name["greenhouse"].status == "succeeded"

            await database_b.execute(
                delete(JobSyncRun).where(JobSyncRun.id == created_runs_b[0].id)
            )
            await database_b.commit()
    finally:
        release_a.set()
        await task_a
        created_run_ids.append(created_runs_a[0].id)


@pytest.mark.anyio
async def test_lock_holder_backend_termination_stops_further_authoritative_writes(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact Critical B3 regression: kill ONLY the PostgreSQL backend
    holding Run A's source lock (not the process, not any Python object)
    while Run A is paused between two records. Run A must fail before
    performing another authoritative write, Run B must be able to acquire
    the same source's lock immediately afterward, and the reference
    correlation must never be regressed by anything Run A does after
    losing the lock."""
    database_a, created_run_ids = job_sync_run_context
    repository_a, created_runs_a = spy_repository(database_a)
    test_token = uuid4().hex

    record_one = make_test_ingestion_record(
        test_token,
        source_name="arbeitnow",
        source_job_id="one",
    )
    record_two = make_test_ingestion_record(
        test_token,
        source_name="arbeitnow",
        source_job_id="two",
    )
    source_a = make_record_source("arbeitnow", (record_one, record_two))

    original_ingest = JobIngestionService.ingest
    first_record_committed = asyncio.Event()
    proceed_to_second_record = asyncio.Event()

    async def paused_ingest(self: JobIngestionService, record, **kwargs):  # noqa: ANN001, ANN201
        if record is record_two:
            await proceed_to_second_record.wait()

        result = await original_ingest(self, record, **kwargs)

        if record is record_one:
            first_record_committed.set()

        return result

    monkeypatch.setattr(JobIngestionService, "ingest", paused_ingest)

    service_a = JobSyncService(
        database_a,
        sources={"arbeitnow": source_a},
        runs=repository_a,
    )

    task_a = asyncio.create_task(service_a.sync_source("arbeitnow", max_pages=1))

    await asyncio.wait_for(first_record_committed.wait(), timeout=5)

    # Discover the exact PostgreSQL backend PID holding Run A's source
    # lock from an independent connection -- pg_locks.pid already carries
    # this, no production introspection hook needed.
    async with isolated_job_sync_database() as (inspector_engine, _inspector_database):
        async with inspector_engine.connect() as inspector:
            backend_pid = await inspector.scalar(
                text(
                    "SELECT pid FROM pg_locks WHERE locktype = 'advisory' "
                    "AND classid = :namespace AND objid = :source_key"
                ),
                {"namespace": SOURCE_SYNC_LOCK_NAMESPACE, "source_key": 1},
            )
            assert backend_pid is not None

            terminated = await inspector.scalar(
                text("SELECT pg_terminate_backend(:pid)"),
                {"pid": backend_pid},
            )
            assert terminated is True
        await inspector_engine.dispose()

    proceed_to_second_record.set()

    with pytest.raises(JobSourceSyncLockLostError):
        await task_a
    created_run_ids.append(created_runs_a[0].id)

    persisted_run_a = await repository_a.get_run_with_sources(created_runs_a[0].id)
    assert persisted_run_a is not None
    assert persisted_run_a.status == "failed"
    persisted_source_a = persisted_run_a.sources[0]
    assert persisted_source_a.status == "failed"
    assert persisted_source_a.error_code == "SOURCE_SYNC_LOCK_LOST"
    # Record one's successful ingestion before the kill is preserved in
    # the persisted partial-progress counts -- B1 semantics unaffected.
    assert persisted_source_a.created == 1

    # Run B can acquire the same source's lock immediately -- the lock
    # died with the backend, not with the (still-alive) test process.
    async with isolated_job_sync_database() as (_engine_b, database_b):
        repository_b, created_runs_b = spy_repository(database_b)
        record_two_again = make_test_ingestion_record(
            test_token,
            source_name="arbeitnow",
            source_job_id="two",
        )
        source_b = make_record_source("arbeitnow", (record_two_again,))
        service_b = JobSyncService(
            database_b,
            sources={"arbeitnow": source_b},
            runs=repository_b,
        )

        summary_b = await service_b.sync_source("arbeitnow", max_pages=1)
        assert summary_b.error is None

        persisted_run_b = await repository_b.get_run_with_sources(created_runs_b[0].id)
        assert persisted_run_b is not None
        assert persisted_run_b.status == "succeeded"

        reference_repository = JobSourceReferenceRepository(database_b)
        reference_two = await reference_repository.get_by_source(
            record_two.source_name,
            record_two.source_job_id,
        )
        assert reference_two is not None
        # B2 invariant: Run A never got to attempt "two" at all (it died
        # before that write), so B's write is the only one this reference
        # ever received -- the pointer correctly reflects B, and cannot
        # later be regressed by an A that no longer exists.
        assert reference_two.last_seen_run_source_id == persisted_run_b.sources[0].id

        await database_b.execute(delete(JobSyncRun).where(JobSyncRun.id == created_runs_b[0].id))
        await database_b.commit()

    reference_repository = JobSourceReferenceRepository(database_a)
    reference_one = await reference_repository.get_by_source(
        record_one.source_name,
        record_one.source_job_id,
    )
    assert reference_one is not None
    assert reference_one.last_seen_run_source_id == persisted_run_a.sources[0].id

    await database_a.execute(
        delete(Job).where(Job.source_name.like(f"job-sync-persist-{test_token}%"))
    )
    await database_a.commit()


@pytest.mark.anyio
async def test_connection_invalidated_error_is_classified_as_lock_lost(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DBAPIError with connection_invalidated=True must be classified as
    SOURCE_SYNC_LOCK_LOST -- proving the classification logic itself,
    independent of a real backend kill."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)
    test_token = uuid4().hex

    record = make_test_ingestion_record(
        test_token,
        source_name="arbeitnow",
        source_job_id="one",
    )
    source = make_record_source("arbeitnow", (record,))

    connection_invalidated_error = DBAPIError(
        "SELECT 1",
        {},
        Exception("server closed the connection unexpectedly"),
        connection_invalidated=True,
    )

    async def failing_ingest(self: JobIngestionService, record: object, **kwargs: object) -> None:
        raise connection_invalidated_error

    monkeypatch.setattr(JobIngestionService, "ingest", failing_ingest)

    service = JobSyncService(
        database,
        sources={"arbeitnow": source},
        runs=repository,
    )

    with pytest.raises(JobSourceSyncLockLostError):
        await service.sync_source("arbeitnow", max_pages=1)
    created_run_ids.append(created_runs[0].id)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)
    assert persisted_run is not None
    assert persisted_run.sources[0].error_code == "SOURCE_SYNC_LOCK_LOST"


@pytest.mark.anyio
async def test_unrelated_sqlalchemy_error_is_classified_as_generic_failure(
    job_sync_run_context: tuple[AsyncSession, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DBAPIError with connection_invalidated=False (e.g. a data/
    constraint error while the backend and lock are still healthy) must
    NOT be mislabeled as a lock loss -- it should surface as the generic
    SOURCE_SYNC_FAILED, still aborting the source (fail-closed)."""
    database, created_run_ids = job_sync_run_context
    repository, created_runs = spy_repository(database)
    test_token = uuid4().hex

    record = make_test_ingestion_record(
        test_token,
        source_name="arbeitnow",
        source_job_id="one",
    )
    source = make_record_source("arbeitnow", (record,))

    unrelated_error = DBAPIError(
        "INSERT INTO jobs (...) VALUES (...)",
        {},
        Exception("value too long for type character varying(255)"),
        connection_invalidated=False,
    )

    async def failing_ingest(self: JobIngestionService, record: object, **kwargs: object) -> None:
        raise unrelated_error

    monkeypatch.setattr(JobIngestionService, "ingest", failing_ingest)

    service = JobSyncService(
        database,
        sources={"arbeitnow": source},
        runs=repository,
    )

    with pytest.raises(JobSyncError) as error_info:
        await service.sync_source("arbeitnow", max_pages=1)
    created_run_ids.append(created_runs[0].id)

    assert not isinstance(error_info.value, JobSourceSyncLockLostError)
    assert not isinstance(error_info.value, JobSourceSyncAlreadyRunningError)

    persisted_run = await repository.get_run_with_sources(created_runs[0].id)
    assert persisted_run is not None
    assert persisted_run.sources[0].error_code == "SOURCE_SYNC_FAILED"
