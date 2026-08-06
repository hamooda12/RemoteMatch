import asyncio
import json
from decimal import Decimal

import httpx
import pytest

from app.integrations.job_sources.remoteok import (
    RemoteOKJobSource,
    RemoteOKSourceError,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def valid_remoteok_job() -> dict[str, object]:
    return {
        "id": "remote-job-123",
        "epoch": 1785924000,
        "date": "2026-08-05T10:00:00+00:00",
        "company": "Remote Company",
        "position": "Senior Python Backend Engineer",
        "description": ("<p>Build APIs using Python and FastAPI.</p><script>ignored()</script>"),
        "location": "USA, Canada",
        "tags": [
            "python",
            "fastapi",
            "senior",
            "full time",
        ],
        "salary_min": 100000,
        "salary_max": 130000,
        "url": ("https://remoteok.com/remote-jobs/remote-senior-python-backend-engineer-123"),
    }


def build_client(
    content: bytes,
    *,
    status_code: int = 200,
) -> httpx.AsyncClient:
    def handler(
        _request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            content=content,
            headers={
                "Content-Type": "application/json",
            },
        )

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.anyio
async def test_fetch_page_maps_remoteok_job() -> None:
    payload = [
        {
            "last_updated": 1785924000,
            "legal": "Link back to Remote OK.",
        },
        valid_remoteok_job(),
    ]

    async with build_client(json.dumps(payload).encode()) as client:
        result = await RemoteOKJobSource(client).fetch_page()

    assert result.page == 1
    assert result.has_next_page is False
    assert result.rejected_count == 0
    assert result.skipped_non_remote_count == 0
    assert len(result.records) == 1

    record = result.records[0]

    assert record.source_name == "remoteok"
    assert record.source_job_id == "remote-job-123"
    assert str(record.source_url) == (
        "https://remoteok.com/remote-jobs/remote-senior-python-backend-engineer-123"
    )

    # Both links must return users to Remote OK.
    assert record.application_url == record.source_url

    assert record.title == ("Senior Python Backend Engineer")
    assert record.company_name == "Remote Company"
    assert record.description == ("Build APIs using Python and FastAPI.")
    assert "ignored" not in record.description

    assert record.location == "USA, Canada"
    assert record.remote_regions == [
        "USA",
        "Canada",
    ]
    assert record.employment_type == "full_time"
    assert record.experience_level == "senior"
    assert record.salary_min == Decimal("100000")
    assert record.salary_max == Decimal("130000")
    assert record.salary_currency == "USD"
    assert record.skills == [
        "Python",
        "FastAPI",
    ]

    assert record.published_at is not None
    assert record.published_at.utcoffset() is not None


@pytest.mark.anyio
async def test_fetch_page_counts_invalid_jobs() -> None:
    invalid_job = valid_remoteok_job()
    invalid_job.pop("company")

    payload = [
        {
            "legal": "Link back to Remote OK.",
        },
        invalid_job,
        valid_remoteok_job(),
    ]

    async with build_client(json.dumps(payload).encode()) as client:
        result = await RemoteOKJobSource(client).fetch_page()

    assert len(result.records) == 1
    assert result.rejected_count == 1


@pytest.mark.anyio
async def test_zero_salary_is_treated_as_unavailable() -> None:
    job = valid_remoteok_job()
    job["salary_min"] = 0
    job["salary_max"] = 0

    payload = [
        {
            "legal": "Link back to Remote OK.",
        },
        job,
    ]

    async with build_client(json.dumps(payload).encode()) as client:
        result = await RemoteOKJobSource(client).fetch_page()

    record = result.records[0]

    assert record.salary_min is None
    assert record.salary_max is None
    assert record.salary_currency is None


@pytest.mark.anyio
async def test_fetch_page_rejects_invalid_json() -> None:
    async with build_client(b"not valid json") as client:
        with pytest.raises(
            RemoteOKSourceError,
            match="invalid JSON",
        ):
            await RemoteOKJobSource(client).fetch_page()


@pytest.mark.anyio
async def test_fetch_page_rejects_invalid_payload() -> None:
    payload = {
        "jobs": [
            valid_remoteok_job(),
        ],
    }

    async with build_client(json.dumps(payload).encode()) as client:
        with pytest.raises(
            RemoteOKSourceError,
            match="invalid response",
        ):
            await RemoteOKJobSource(client).fetch_page()


@pytest.mark.anyio
async def test_fetch_page_wraps_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async with build_client(
        b"",
        status_code=503,
    ) as client:
        with pytest.raises(
            RemoteOKSourceError,
            match="Unable to fetch jobs",
        ):
            await RemoteOKJobSource(client).fetch_page()


@pytest.mark.anyio
async def test_fetch_page_retries_transient_failure_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    call_count = 0
    payload = [valid_remoteok_job()]

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        del request
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return httpx.Response(status_code=503, content=b"")

        return httpx.Response(
            status_code=200,
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await RemoteOKJobSource(client).fetch_page()

    assert call_count == 2
    assert len(result.records) == 1


@pytest.mark.anyio
async def test_fetch_page_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.integrations.job_sources.remoteok.MAX_SOURCE_RESPONSE_BYTES",
        10,
    )

    async with build_client(b"response larger than ten bytes") as client:
        with pytest.raises(
            RemoteOKSourceError,
            match="exceeded the allowed size",
        ):
            await RemoteOKJobSource(client).fetch_page()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "page",
    [
        0,
        2,
        100,
    ],
)
async def test_fetch_page_rejects_unsupported_pages(
    page: int,
) -> None:
    source = RemoteOKJobSource()

    with pytest.raises(
        ValueError,
        match="supports only page 1",
    ):
        await source.fetch_page(page=page)
