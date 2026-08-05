from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from app.integrations.job_sources import (
    ARBEITNOW_SOURCE_NAME,
    HIMALAYAS_SOURCE_NAME,
    JobSourceError,
    JobSourceFetchResult,
    available_job_source_names,
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

    expected_sources = (
        ARBEITNOW_SOURCE_NAME,
        HIMALAYAS_SOURCE_NAME,
    )

    assert tuple(registry) == expected_sources
    assert available_job_source_names() == expected_sources

    arbeitnow = registry[ARBEITNOW_SOURCE_NAME]
    himalayas = registry[HIMALAYAS_SOURCE_NAME]

    assert arbeitnow.name == (ARBEITNOW_SOURCE_NAME)
    assert arbeitnow.max_pages == 5

    assert himalayas.name == (HIMALAYAS_SOURCE_NAME)
    assert himalayas.max_pages == 5


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
