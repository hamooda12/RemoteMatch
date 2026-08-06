import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

import app.integrations.job_sources.jobicy as jobicy_module
from app.integrations.job_sources.jobicy import (
    JobicyJobSource,
    JobicySourceError,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def valid_job(
    **overrides: Any,
) -> dict[str, object]:
    job: dict[str, object] = {
        "id": 123456,
        "url": ("https://jobicy.com/jobs/123456-python-engineer"),
        "jobSlug": "123456-python-engineer",
        "jobTitle": "Python Backend Engineer",
        "companyName": ("Remote &#038; Secure"),
        "companyLogo": ("https://example.com/logo.png"),
        "jobIndustry": [
            "Software Engineering",
            "Python",
            "FastAPI",
        ],
        "jobType": [
            "Full-Time",
        ],
        "jobGeo": "Germany, Ireland",
        "jobLevel": "Midweight",
        "jobExcerpt": "Build secure APIs.",
        "jobDescription": ("<p>Build Python APIs with <strong>FastAPI</strong>.</p>"),
        "pubDate": ("2026-08-05T07:25:07+00:00"),
        "salaryMin": 50,
        "salaryMax": 60,
        "salaryCurrency": "USD",
        "salaryPeriod": "hourly",
    }
    job.update(overrides)

    return job


def valid_payload(
    jobs: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "apiVersion": "2.2.15",
        "documentationUrl": ("https://jobi.cy/apidocs"),
        "friendlyNotice": ("Please credit Jobicy."),
        "jobCount": len(jobs),
        "lastUpdate": ("2026-08-05T07:25:07+00:00"),
        "appliedFilters": {
            "count": 100,
        },
        "jobs": jobs,
    }


@pytest.mark.anyio
async def test_fetch_maps_jobicy_job() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.url.params["count"] == "100"

        return httpx.Response(
            200,
            json=valid_payload([valid_job()]),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await JobicyJobSource(client).fetch_page()

    assert result.page == 1
    assert result.has_next_page is False
    assert result.rejected_count == 0
    assert result.skipped_non_remote_count == 0
    assert len(result.records) == 1

    record = result.records[0]

    assert record.source_name == "jobicy"
    assert record.source_job_id == "123456"
    assert str(record.source_url) == ("https://jobicy.com/jobs/123456-python-engineer")
    assert record.title == ("Python Backend Engineer")
    assert record.company_name == ("Remote & Secure")
    assert record.description == ("Build Python APIs with FastAPI.")
    assert record.location == ("Germany, Ireland")
    assert record.remote_regions == [
        "Germany",
        "Ireland",
    ]
    assert record.employment_type == "full_time"
    assert record.experience_level == "mid_level"
    assert record.salary_min == Decimal("104000.00")
    assert record.salary_max == Decimal("124800.00")
    assert record.salary_currency == "USD"
    assert record.skills == [
        "Python",
        "FastAPI",
    ]
    assert record.published_at == datetime(
        2026,
        8,
        5,
        7,
        25,
        7,
        tzinfo=UTC,
    )


@pytest.mark.anyio
async def test_supports_worldwide_job_without_salary() -> None:
    job = valid_job(
        id=123457,
        url=("https://jobicy.com/jobs/123457-support-engineer"),
        jobTitle="Support Engineer",
        jobGeo="Anywhere",
        jobType=["Part-Time"],
        jobLevel="Entry-Level",
        pubDate="2026-08-05T07:25:07",
        salaryMin=None,
        salaryMax=None,
        salaryCurrency=None,
        salaryPeriod=None,
    )

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            json=valid_payload([job]),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await JobicyJobSource(client).fetch_page()

    record = result.records[0]

    assert record.location == "Worldwide"
    assert record.remote_regions == [
        "Worldwide",
    ]
    assert record.employment_type == "part_time"
    assert record.experience_level == "entry_level"
    assert record.salary_min is None
    assert record.salary_max is None
    assert record.salary_currency is None
    assert record.published_at is not None
    assert record.published_at.tzinfo is not None


@pytest.mark.anyio
async def test_counts_invalid_jobs() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            json=valid_payload(
                [
                    valid_job(),
                    {
                        "id": 999,
                        "jobTitle": "",
                    },
                ]
            ),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await JobicyJobSource(client).fetch_page()

    assert len(result.records) == 1
    assert result.rejected_count == 1


@pytest.mark.anyio
async def test_rejects_invalid_payload() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not valid JSON",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            JobicySourceError,
            match="invalid response",
        ):
            await JobicyJobSource(client).fetch_page()


@pytest.mark.anyio
async def test_wraps_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": "Too many requests",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            JobicySourceError,
            match="Unable to fetch",
        ):
            await JobicyJobSource(client).fetch_page()


@pytest.mark.anyio
async def test_fetch_page_retries_transient_failure_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    call_count = 0

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        del request
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            return httpx.Response(
                503,
                json={"error": "Unavailable"},
            )

        return httpx.Response(
            200,
            json=valid_payload([valid_job()]),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await JobicyJobSource(client).fetch_page()

    assert call_count == 2
    assert len(result.records) == 1


@pytest.mark.anyio
async def test_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobicy_module,
        "MAX_SOURCE_RESPONSE_BYTES",
        10,
    )

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x" * 11,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            JobicySourceError,
            match="exceeded the allowed size",
        ):
            await JobicyJobSource(client).fetch_page()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "page",
    [
        0,
        2,
    ],
)
async def test_rejects_unsupported_page(
    page: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="only page 1",
    ):
        await JobicyJobSource().fetch_page(page)
