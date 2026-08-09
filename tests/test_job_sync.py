from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call
from uuid import uuid4

import pytest

from app.integrations.job_sources.arbeitnow import (
    ARBEITNOW_SOURCE_NAME,
    ArbeitnowSourceError,
)
from app.models.job_sync_run import JobSyncRun, JobSyncRunSource
from app.repositories.job_sync_run import JobSyncRunRepository
from app.services.job_ingestion import (
    JobIngestionAction,
    JobIngestionConflictError,
)
from app.services.job_sync import (
    JobSyncError,
    JobSyncService,
)


@dataclass(slots=True)
class FakeFetchResult:
    records: tuple[object, ...]
    page: int
    has_next_page: bool
    rejected_records: int = 0
    skipped_non_remote_records: int = 0

    @property
    def has_next(self) -> bool:
        return self.has_next_page

    @property
    def rejected_record_count(self) -> int:
        return self.rejected_records

    @property
    def rejected_count(self) -> int:
        return self.rejected_records

    @property
    def skipped_non_remote_count(self) -> int:
        return self.skipped_non_remote_records

    @property
    def skipped_non_remote_record_count(self) -> int:
        return self.skipped_non_remote_records

    @property
    def skipped_non_remote(self) -> int:
        return self.skipped_non_remote_records


def fake_database() -> Mock:
    database = Mock()
    database.commit = AsyncMock()
    return database


def fake_job_sync_run_repository() -> Mock:
    repository = Mock()
    repository.create_run = AsyncMock(
        side_effect=lambda: JobSyncRun(
            id=uuid4(),
            status="running",
            started_at=datetime.now(UTC),
        )
    )
    repository.create_run_source = AsyncMock(
        side_effect=lambda run_id, source_name: JobSyncRunSource(
            id=uuid4(),
            run_id=run_id,
            source_name=source_name,
            status="running",
            started_at=datetime.now(UTC),
            pages_fetched=0,
            fetched_records=0,
            created=0,
            updated=0,
            duplicates=0,
            conflicts=0,
            rejected=0,
            skipped_non_remote=0,
        )
    )
    repository.complete_run_source = JobSyncRunRepository.complete_run_source
    repository.complete_run = JobSyncRunRepository.complete_run

    return repository


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_sync_processes_multiple_pages_and_counts_results() -> None:
    first_page_records = (
        object(),
        object(),
    )
    second_page_records = (
        object(),
        object(),
        object(),
    )

    source = SimpleNamespace(
        fetch_page=AsyncMock(
            side_effect=[
                FakeFetchResult(
                    records=first_page_records,
                    page=1,
                    has_next_page=True,
                    rejected_records=1,
                    skipped_non_remote_records=2,
                ),
                FakeFetchResult(
                    records=second_page_records,
                    page=2,
                    has_next_page=False,
                    rejected_records=2,
                    skipped_non_remote_records=1,
                ),
            ]
        )
    )

    database = fake_database()
    service = JobSyncService(
        database,
        arbeitnow_source=source,
        runs=fake_job_sync_run_repository(),
    )

    ingest = AsyncMock(
        side_effect=[
            SimpleNamespace(
                action=JobIngestionAction.CREATED,
            ),
            SimpleNamespace(
                action=JobIngestionAction.UPDATED,
            ),
            SimpleNamespace(
                action=JobIngestionAction.DUPLICATE,
            ),
            JobIngestionConflictError(),
            SimpleNamespace(
                action=JobIngestionAction.CREATED,
            ),
        ]
    )
    service.ingestion.ingest = ingest

    summary = await service.sync_arbeitnow(max_pages=2)

    assert summary.source_name == ARBEITNOW_SOURCE_NAME
    assert summary.pages_fetched == 2
    assert summary.fetched_records == 5
    assert summary.created == 2
    assert summary.updated == 1
    assert summary.duplicates == 1
    assert summary.conflicts == 1
    assert summary.rejected == 3
    assert summary.skipped_non_remote == 3

    assert source.fetch_page.await_args_list == [
        call(page=1),
        call(page=2),
    ]
    assert ingest.await_count == 5

    observed_times = {awaited_call.kwargs["observed_at"] for awaited_call in ingest.await_args_list}

    assert len(observed_times) == 1

    observed_at = observed_times.pop()
    assert observed_at.tzinfo is not None


@pytest.mark.anyio
async def test_sync_respects_maximum_page_limit() -> None:
    source = SimpleNamespace(
        fetch_page=AsyncMock(
            return_value=FakeFetchResult(
                records=(object(),),
                page=1,
                has_next_page=True,
            )
        )
    )

    database = fake_database()
    service = JobSyncService(
        database,
        arbeitnow_source=source,
        runs=fake_job_sync_run_repository(),
    )

    ingest = AsyncMock(
        return_value=SimpleNamespace(
            action=JobIngestionAction.CREATED,
        )
    )
    service.ingestion.ingest = ingest

    summary = await service.sync_arbeitnow(max_pages=1)

    assert summary.pages_fetched == 1
    assert summary.fetched_records == 1
    assert summary.created == 1

    source.fetch_page.assert_awaited_once_with(page=1)
    ingest.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "max_pages",
    [
        0,
        6,
    ],
)
async def test_sync_rejects_invalid_page_limits(
    max_pages: int,
) -> None:
    source = SimpleNamespace(
        fetch_page=AsyncMock(),
    )

    database = fake_database()
    service = JobSyncService(
        database,
        arbeitnow_source=source,
        runs=fake_job_sync_run_repository(),
    )

    with pytest.raises(
        ValueError,
        match="max_pages must be between 1 and 5",
    ):
        await service.sync_arbeitnow(
            max_pages=max_pages,
        )

    source.fetch_page.assert_not_awaited()


@pytest.mark.anyio
async def test_sync_wraps_source_failures() -> None:
    source = SimpleNamespace(
        fetch_page=AsyncMock(
            side_effect=ArbeitnowSourceError(
                "The source is unavailable.",
            )
        )
    )

    database = fake_database()
    service = JobSyncService(
        database,
        arbeitnow_source=source,
        runs=fake_job_sync_run_repository(),
    )

    with pytest.raises(
        JobSyncError,
        match="page 1",
    ) as error_info:
        await service.sync_arbeitnow(max_pages=1)

    assert isinstance(
        error_info.value.__cause__,
        ArbeitnowSourceError,
    )

    source.fetch_page.assert_awaited_once_with(page=1)
