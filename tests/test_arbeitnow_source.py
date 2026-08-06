import asyncio
from datetime import UTC, datetime

import httpx
import pytest

import app.integrations.job_sources.arbeitnow as arbeitnow
from app.integrations.job_sources.arbeitnow import (
    ARBEITNOW_SOURCE_NAME,
    ArbeitnowJobSource,
    ArbeitnowSourceError,
    html_to_plain_text,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def valid_source_job(
    *,
    remote: bool = True,
) -> dict[str, object]:
    return {
        "slug": "junior-python-engineer-123",
        "company_name": "Example Company",
        "title": "Junior Python Engineer",
        "description": (
            "&lt;p&gt;Build APIs with Python &amp;amp; FastAPI.&lt;/p&gt;<script>ignored()</script>"
        ),
        "remote": remote,
        "url": ("https://www.arbeitnow.com/jobs/companies/example/junior-python-engineer-123"),
        "tags": [
            "Python",
            "Remote",
            "FastAPI",
        ],
        "job_types": [
            "Full Time",
            "Junior",
        ],
        "location": " Worldwide ",
        "created_at": int(
            datetime(
                2026,
                8,
                3,
                10,
                0,
                tzinfo=UTC,
            ).timestamp()
        ),
    }


def source_payload(
    jobs: list[dict[str, object]],
    *,
    has_next_page: bool = False,
) -> dict[str, object]:
    return {
        "data": jobs,
        "links": {
            "first": ("https://www.arbeitnow.com/api/job-board-api?page=1"),
            "last": None,
            "prev": None,
            "next": (
                "https://www.arbeitnow.com/api/job-board-api?page=2" if has_next_page else None
            ),
        },
        "meta": {
            "current_page": 1,
        },
    }


def test_html_to_plain_text_removes_markup_and_scripts() -> None:
    source_html = (
        "&lt;div&gt;Hello &amp;amp; welcome&lt;/div&gt;"
        "<script>stealData()</script>"
        "<p>Python <strong>FastAPI</strong></p>"
    )

    assert html_to_plain_text(source_html) == ("Hello & welcome\nPython FastAPI")


@pytest.mark.anyio
async def test_fetch_page_maps_only_remote_jobs() -> None:
    def handle_request(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["page"] == "2"
        assert request.headers["accept"] == "application/json"
        assert request.headers["user-agent"] == ("RemoteMatch/0.1")

        return httpx.Response(
            status_code=200,
            json=source_payload(
                [
                    valid_source_job(remote=True),
                    valid_source_job(remote=False),
                ],
                has_next_page=True,
            ),
        )

    transport = httpx.MockTransport(handle_request)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        result = await ArbeitnowJobSource(client).fetch_page(page=2)

    assert result.page == 2
    assert result.has_next_page is True
    assert result.rejected_count == 0
    assert result.skipped_non_remote_count == 1
    assert len(result.records) == 1

    record = result.records[0]

    assert record.source_name == ARBEITNOW_SOURCE_NAME
    assert record.source_job_id == ("junior-python-engineer-123")
    assert str(record.source_url) == (
        "https://www.arbeitnow.com/jobs/companies/example/junior-python-engineer-123"
    )
    assert record.application_url == record.source_url
    assert record.title == "Junior Python Engineer"
    assert record.company_name == "Example Company"
    assert record.description == ("Build APIs with Python & FastAPI.")
    assert record.location == "Worldwide"
    assert record.remote_regions == ["Worldwide"]
    assert record.employment_type == "full_time"
    assert record.experience_level == "junior"
    assert record.skills == [
        "Python",
        "FastAPI",
    ]
    assert record.is_remote is True
    assert record.published_at == datetime(
        2026,
        8,
        3,
        10,
        0,
        tzinfo=UTC,
    )


@pytest.mark.anyio
async def test_fetch_page_counts_invalid_and_non_remote_jobs() -> None:
    invalid_job = {
        "remote": True,
        "title": "Missing required fields",
    }

    def handle_request(
        request: httpx.Request,
    ) -> httpx.Response:
        del request

        return httpx.Response(
            status_code=200,
            json=source_payload(
                [
                    invalid_job,
                    valid_source_job(remote=False),
                ]
            ),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle_request),
    ) as client:
        result = await ArbeitnowJobSource(client).fetch_page()

    assert result.records == ()
    assert result.rejected_count == 1
    assert result.skipped_non_remote_count == 1
    assert result.has_next_page is False


@pytest.mark.anyio
async def test_fetch_page_rejects_invalid_payload() -> None:
    def handle_request(
        request: httpx.Request,
    ) -> httpx.Response:
        del request

        return httpx.Response(
            status_code=200,
            json={"unexpected": []},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle_request),
    ) as client:
        with pytest.raises(
            ArbeitnowSourceError,
            match="invalid response",
        ):
            await ArbeitnowJobSource(client).fetch_page()


@pytest.mark.anyio
async def test_fetch_page_handles_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    def handle_request(
        request: httpx.Request,
    ) -> httpx.Response:
        del request

        return httpx.Response(
            status_code=503,
            json={"detail": "Unavailable"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle_request),
    ) as client:
        with pytest.raises(
            ArbeitnowSourceError,
            match="Unable to fetch",
        ):
            await ArbeitnowJobSource(client).fetch_page()


@pytest.mark.anyio
async def test_fetch_page_retries_transient_failure_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    call_count = 0

    def handle_request(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return httpx.Response(
                status_code=503,
                json={"detail": "Unavailable"},
            )

        return httpx.Response(
            status_code=200,
            json=source_payload(
                [valid_source_job(remote=True)],
            ),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle_request),
    ) as client:
        result = await ArbeitnowJobSource(client).fetch_page()

    assert call_count == 2
    assert len(result.records) == 1
    assert result.records[0].source_job_id == "junior-python-engineer-123"


@pytest.mark.anyio
async def test_fetch_page_does_not_retry_non_retryable_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay
        raise AssertionError("sleep should not be called for a non-retryable failure")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    call_count = 0

    def handle_request(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal call_count
        call_count += 1

        return httpx.Response(
            status_code=404,
            json={"detail": "Not Found"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle_request),
    ) as client:
        with pytest.raises(
            ArbeitnowSourceError,
            match="Unable to fetch",
        ):
            await ArbeitnowJobSource(client).fetch_page()

    assert call_count == 1


@pytest.mark.anyio
async def test_fetch_page_raises_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    call_count = 0

    def handle_request(
        request: httpx.Request,
    ) -> httpx.Response:
        nonlocal call_count
        call_count += 1

        return httpx.Response(
            status_code=503,
            json={"detail": "Unavailable"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle_request),
    ) as client:
        with pytest.raises(
            ArbeitnowSourceError,
            match="Unable to fetch",
        ) as error_info:
            await ArbeitnowJobSource(client).fetch_page()

    assert call_count == 3
    assert isinstance(error_info.value.__cause__, httpx.HTTPStatusError)
    assert error_info.value.__cause__.response.status_code == 503


@pytest.mark.anyio
async def test_fetch_page_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        arbeitnow,
        "MAX_SOURCE_RESPONSE_BYTES",
        10,
    )

    def handle_request(
        request: httpx.Request,
    ) -> httpx.Response:
        del request

        return httpx.Response(
            status_code=200,
            content=b"x" * 11,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle_request),
    ) as client:
        with pytest.raises(
            ArbeitnowSourceError,
            match="exceeded the allowed size",
        ):
            await ArbeitnowJobSource(client).fetch_page()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "page",
    [
        0,
        10_001,
    ],
)
async def test_fetch_page_rejects_invalid_page(
    page: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="page must be between",
    ):
        await ArbeitnowJobSource().fetch_page(page)
