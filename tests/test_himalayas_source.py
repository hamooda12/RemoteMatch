import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

import app.integrations.job_sources.himalayas as himalayas_module
from app.integrations.job_sources.himalayas import (
    HimalayasJobSource,
    HimalayasSourceError,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def valid_job(
    **overrides: Any,
) -> dict[str, object]:
    job: dict[str, object] = {
        "title": "Senior Python Engineer",
        "excerpt": "Build secure Python APIs.",
        "companyName": "Remote Company",
        "companySlug": "remote-company",
        "companyLogo": ("https://example.com/logo.png"),
        "employmentType": "Contractor",
        "minSalary": 50,
        "maxSalary": 60,
        "salaryPeriod": "hourly",
        "seniority": ["Mid-level"],
        "currency": "USD",
        "locationRestrictions": [],
        "timezoneRestrictions": [
            -5,
            0,
            2,
        ],
        "categories": [
            "Python",
            "FastAPI",
        ],
        "parentCategories": [
            "Engineering",
        ],
        "description": ("<p>Build Python APIs with <strong>FastAPI</strong>.</p>"),
        "pubDate": 1_780_000_000,
        "expiryDate": 1_782_592_000,
        "applicationLink": (
            "https://himalayas.app/companies/remote-company/jobs/senior-python-engineer"
        ),
        "guid": ("https://himalayas.app/companies/remote-company/jobs/senior-python-engineer"),
    }
    job.update(overrides)

    return job


def valid_payload(
    jobs: list[dict[str, object]],
    *,
    offset: int = 0,
    total_count: int | None = None,
) -> dict[str, object]:
    return {
        "updatedAt": 1_780_000_000,
        "offset": offset,
        "limit": 20,
        "totalCount": (len(jobs) if total_count is None else total_count),
        "jobs": jobs,
    }


@pytest.mark.anyio
async def test_fetch_page_maps_himalayas_job() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.url.params["limit"] == "20"
        assert request.url.params["offset"] == "20"

        return httpx.Response(
            200,
            json=valid_payload(
                [valid_job()],
                offset=20,
                total_count=40,
            ),
        )

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        transport=transport,
    ) as client:
        result = await HimalayasJobSource(client).fetch_page(page=2)

    assert result.page == 2
    assert result.has_next_page is True
    assert result.rejected_count == 0
    assert result.skipped_non_remote_count == 0
    assert len(result.records) == 1

    record = result.records[0]

    assert record.source_name == "himalayas"
    assert record.title == "Senior Python Engineer"
    assert record.company_name == "Remote Company"
    assert record.description == ("Build Python APIs with FastAPI.")
    assert record.location == "Worldwide"
    assert record.remote_regions == [
        "Worldwide",
    ]
    assert record.employment_type == "contract"
    assert record.experience_level == "mid_level"
    assert record.salary_min == Decimal("104000.00")
    assert record.salary_max == Decimal("124800.00")
    assert record.salary_currency == "USD"
    assert record.skills == [
        "Python",
        "FastAPI",
    ]
    assert record.published_at == datetime.fromtimestamp(
        1_780_000_000,
        tz=UTC,
    )


@pytest.mark.anyio
async def test_supports_structured_locations_and_milliseconds() -> None:
    job = valid_job(
        locationRestrictions=[
            {
                "alpha2": "PS",
                "name": "Palestine",
                "slug": "palestine",
            },
            {
                "alpha2": "DE",
                "name": "Germany",
                "slug": "germany",
            },
        ],
        employmentType="Full Time",
        seniority=["Entry-level"],
        minSalary=5_000,
        maxSalary=6_000,
        salaryPeriod="monthly",
        pubDate=1_780_000_000_000,
        expiryDate=1_782_592_000_000,
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
        result = await HimalayasJobSource(client).fetch_page()

    record = result.records[0]

    assert record.location == ("Palestine, Germany")
    assert record.remote_regions == [
        "Palestine",
        "Germany",
    ]
    assert record.employment_type == "full_time"
    assert record.experience_level == "entry_level"
    assert record.salary_min == Decimal("60000.00")
    assert record.salary_max == Decimal("72000.00")
    assert record.published_at == datetime.fromtimestamp(
        1_780_000_000,
        tz=UTC,
    )


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
                        "title": "",
                    },
                ]
            ),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await HimalayasJobSource(client).fetch_page()

    assert len(result.records) == 1
    assert result.rejected_count == 1
    assert result.has_next_page is False


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
            HimalayasSourceError,
            match="invalid response",
        ):
            await HimalayasJobSource(client).fetch_page()


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
            503,
            json={
                "error": "Unavailable",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            HimalayasSourceError,
            match="Unable to fetch",
        ):
            await HimalayasJobSource(client).fetch_page()


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
        result = await HimalayasJobSource(client).fetch_page()

    assert call_count == 2
    assert len(result.records) == 1


@pytest.mark.anyio
async def test_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        himalayas_module,
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
            HimalayasSourceError,
            match="exceeded the allowed size",
        ):
            await HimalayasJobSource(client).fetch_page()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "page",
    [
        0,
        10_001,
    ],
)
async def test_rejects_invalid_page(
    page: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="page must be between",
    ):
        await HimalayasJobSource().fetch_page(page)
