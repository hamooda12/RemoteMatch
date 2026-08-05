from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from app.integrations.job_sources import (
    JobSourceError,
    JobSourceFetchResult,
    build_job_source_registry,
)
from app.services.job_sync import (
    JobSyncError,
    JobSyncService,
)


class FakeSourceError(JobSourceError):
    """Raised by a fake job source during tests."""


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_registry_contains_configured_sources() -> None:
    registry = build_job_source_registry()

    assert tuple(registry) == (
        "arbeitnow",
        "himalayas",
        "jobicy",
        "remoteok",
    )


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
        Mock(),
        sources={
            source.name: source,
        },
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

    service = JobSyncService(
        Mock(),
        sources={
            first_source.name: first_source,
            second_source.name: second_source,
        },
    )

    summaries = await service.sync_all(max_pages=1)

    assert [summary.source_name for summary in summaries] == [
        "first",
        "second",
    ]

    first_source.fetch_page.assert_awaited_once_with(page=1)
    second_source.fetch_page.assert_awaited_once_with(page=1)


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
        Mock(),
        sources={
            paginated_source.name: (paginated_source),
            single_page_source.name: (single_page_source),
        },
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
async def test_sync_rejects_unknown_source() -> None:
    service = JobSyncService(
        Mock(),
        sources={},
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
        Mock(),
        sources={
            source.name: source,
        },
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
