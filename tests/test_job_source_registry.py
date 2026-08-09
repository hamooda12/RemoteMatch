from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.integrations.job_sources import (
    JobSourceError,
    JobSourceFetchResult,
    build_job_source_registry,
)
from app.models.job_sync_run import JobSyncRun, JobSyncRunSource
from app.repositories.job_sync_run import JobSyncRunRepository
from app.services.job_sync import (
    JobSyncError,
    JobSyncService,
)


class FakeSourceError(JobSourceError):
    """Raised by a fake job source during tests."""


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


def test_registry_contains_configured_sources() -> None:
    registry = build_job_source_registry()

    assert tuple(registry) == (
        "arbeitnow",
        "greenhouse",
        "himalayas",
        "jobicy",
        "remoteok",
    )


def test_registry_enables_all_five_sources_by_default() -> None:
    settings = get_settings().model_copy()

    registry = build_job_source_registry(settings)

    assert set(registry) == {
        "arbeitnow",
        "greenhouse",
        "himalayas",
        "jobicy",
        "remoteok",
    }


def test_registry_excludes_a_single_disabled_source() -> None:
    settings = get_settings().model_copy(
        update={"job_source_greenhouse_enabled": False},
    )

    registry = build_job_source_registry(settings)

    assert "greenhouse" not in registry
    assert set(registry) == {
        "arbeitnow",
        "himalayas",
        "jobicy",
        "remoteok",
    }


def test_registry_excludes_exactly_the_disabled_sources() -> None:
    settings = get_settings().model_copy(
        update={
            "job_source_himalayas_enabled": False,
            "job_source_remoteok_enabled": False,
        },
    )

    registry = build_job_source_registry(settings)

    assert set(registry) == {
        "arbeitnow",
        "greenhouse",
        "jobicy",
    }


def test_registry_is_empty_when_every_source_is_disabled() -> None:
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


@pytest.mark.anyio
async def test_syncs_generic_source_by_name() -> None:
    source = SimpleNamespace(
        name="fake",
        max_pages=3,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(
                records=(),
                page=1,
                has_next_page=False,
            )
        ),
    )

    service = JobSyncService(
        fake_database(),
        sources={
            source.name: source,
        },
        runs=fake_job_sync_run_repository(),
    )

    summary = await service.sync_source(
        "fake",
        max_pages=1,
    )

    assert summary.source_name == "fake"
    assert summary.pages_fetched == 1
    assert summary.fetched_records == 0

    source.fetch_page.assert_awaited_once_with(page=1)


@pytest.mark.anyio
async def test_sync_all_processes_every_source() -> None:
    first_source = SimpleNamespace(
        name="first",
        max_pages=2,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(
                records=(),
                page=1,
                has_next_page=False,
            )
        ),
    )

    second_source = SimpleNamespace(
        name="second",
        max_pages=2,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(
                records=(),
                page=1,
                has_next_page=False,
            )
        ),
    )

    runs = fake_job_sync_run_repository()
    service = JobSyncService(
        fake_database(),
        sources={
            first_source.name: first_source,
            second_source.name: second_source,
        },
        runs=runs,
    )

    summaries = await service.sync_all(max_pages=1)

    assert [summary.source_name for summary in summaries] == [
        "first",
        "second",
    ]

    first_source.fetch_page.assert_awaited_once_with(page=1)
    second_source.fetch_page.assert_awaited_once_with(page=1)

    assert runs.create_run.await_count == 1


@pytest.mark.anyio
async def test_sync_all_respects_each_source_page_limit() -> None:
    paginated_source = SimpleNamespace(
        name="paginated",
        max_pages=3,
        fetch_page=AsyncMock(
            side_effect=[
                JobSourceFetchResult(
                    records=(),
                    page=1,
                    has_next_page=True,
                ),
                JobSourceFetchResult(
                    records=(),
                    page=2,
                    has_next_page=True,
                ),
                JobSourceFetchResult(
                    records=(),
                    page=3,
                    has_next_page=True,
                ),
            ]
        ),
    )

    single_page_source = SimpleNamespace(
        name="single-page",
        max_pages=1,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(
                records=(),
                page=1,
                has_next_page=True,
            )
        ),
    )

    service = JobSyncService(
        fake_database(),
        sources={
            paginated_source.name: (paginated_source),
            single_page_source.name: (single_page_source),
        },
        runs=fake_job_sync_run_repository(),
    )

    summaries = await service.sync_all(max_pages=3)

    assert [summary.source_name for summary in summaries] == [
        "paginated",
        "single-page",
    ]

    assert paginated_source.fetch_page.await_args_list == [
        call(page=1),
        call(page=2),
        call(page=3),
    ]
    single_page_source.fetch_page.assert_awaited_once_with(page=1)


@pytest.mark.anyio
async def test_sync_all_continues_after_one_source_fails() -> None:
    first_source = SimpleNamespace(
        name="first",
        max_pages=1,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(
                records=(),
                page=1,
                has_next_page=False,
            )
        ),
    )

    second_source = SimpleNamespace(
        name="second",
        max_pages=1,
        fetch_page=AsyncMock(side_effect=FakeSourceError("boom")),
    )

    third_source = SimpleNamespace(
        name="third",
        max_pages=1,
        fetch_page=AsyncMock(
            return_value=JobSourceFetchResult(
                records=(),
                page=1,
                has_next_page=False,
            )
        ),
    )

    runs = fake_job_sync_run_repository()
    service = JobSyncService(
        fake_database(),
        sources={
            first_source.name: first_source,
            second_source.name: second_source,
            third_source.name: third_source,
        },
        runs=runs,
    )

    summaries = await service.sync_all(max_pages=1)

    assert [summary.source_name for summary in summaries] == [
        "first",
        "second",
        "third",
    ]

    first_source.fetch_page.assert_awaited_once_with(page=1)
    third_source.fetch_page.assert_awaited_once_with(page=1)

    assert summaries[0].error is None
    assert summaries[0].pages_fetched == 1

    assert summaries[1].error is not None
    assert "second" in summaries[1].error
    assert "page 1" in summaries[1].error

    assert summaries[2].error is None
    assert summaries[2].pages_fetched == 1

    assert runs.create_run.await_count == 1


@pytest.mark.anyio
async def test_sync_all_reports_multiple_failures_independently() -> None:
    first_source = SimpleNamespace(
        name="first",
        max_pages=1,
        fetch_page=AsyncMock(side_effect=FakeSourceError("first is down")),
    )

    second_source = SimpleNamespace(
        name="second",
        max_pages=1,
        fetch_page=AsyncMock(side_effect=FakeSourceError("second is down")),
    )

    service = JobSyncService(
        fake_database(),
        sources={
            first_source.name: first_source,
            second_source.name: second_source,
        },
        runs=fake_job_sync_run_repository(),
    )

    summaries = await service.sync_all(max_pages=1)

    assert [summary.source_name for summary in summaries] == [
        "first",
        "second",
    ]

    first_source.fetch_page.assert_awaited_once_with(page=1)
    second_source.fetch_page.assert_awaited_once_with(page=1)

    assert summaries[0].error is not None
    assert "first" in summaries[0].error

    assert summaries[1].error is not None
    assert "second" in summaries[1].error

    assert summaries[0].error != summaries[1].error


@pytest.mark.anyio
async def test_sync_all_raises_without_creating_a_run_when_no_sources() -> None:
    runs = fake_job_sync_run_repository()
    service = JobSyncService(
        fake_database(),
        sources={},
        runs=runs,
    )

    with pytest.raises(
        ValueError,
        match="No job sources are enabled.",
    ):
        await service.sync_all(max_pages=1)

    runs.create_run.assert_not_awaited()


@pytest.mark.anyio
async def test_sync_source_rejects_a_disabled_source_not_in_registry() -> None:
    """A disabled source is simply absent from the injected registry, so a
    direct sync_source() request for it fails the same way an unknown
    source name would."""
    service = JobSyncService(
        fake_database(),
        sources={"arbeitnow": SimpleNamespace(name="arbeitnow", max_pages=1)},
        runs=fake_job_sync_run_repository(),
    )

    with pytest.raises(
        ValueError,
        match="Unknown job source 'greenhouse'",
    ):
        await service.sync_source(
            "greenhouse",
            max_pages=1,
        )


@pytest.mark.anyio
async def test_sync_rejects_unknown_source() -> None:
    service = JobSyncService(
        fake_database(),
        sources={},
        runs=fake_job_sync_run_repository(),
    )

    with pytest.raises(
        ValueError,
        match="Unknown job source",
    ):
        await service.sync_source(
            "unknown",
            max_pages=1,
        )


@pytest.mark.anyio
async def test_generic_source_failure_is_wrapped() -> None:
    source = SimpleNamespace(
        name="broken",
        max_pages=2,
        fetch_page=AsyncMock(side_effect=FakeSourceError("Source unavailable.")),
    )

    service = JobSyncService(
        fake_database(),
        sources={
            source.name: source,
        },
        runs=fake_job_sync_run_repository(),
    )

    with pytest.raises(
        JobSyncError,
        match="broken page 1",
    ) as error_info:
        await service.sync_source(
            "broken",
            max_pages=1,
        )

    assert isinstance(
        error_info.value.__cause__,
        FakeSourceError,
    )

    assert source.fetch_page.await_args_list == [
        call(page=1),
    ]
