import asyncio
import json
from collections.abc import Mapping

import httpx
import pytest

from app.integrations.job_sources.greenhouse import (
    GreenhouseJobSource,
    GreenhouseSourceError,
)
from app.integrations.job_sources.greenhouse_boards import (
    GreenhouseBoard,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def valid_greenhouse_job(
    *,
    job_id: int = 123,
) -> dict[str, object]:
    return {
        "id": job_id,
        "title": "Senior Python Backend Engineer",
        "updated_at": "2026-08-05T10:00:00+00:00",
        "location": {
            "name": "Remote - Europe, Middle East",
        },
        "absolute_url": (f"https://boards.greenhouse.io/example/jobs/{job_id}"),
        "content": (
            "&lt;p&gt;This is a full-time position.&lt;/p&gt;"
            "&lt;p&gt;Build APIs with Python, FastAPI, "
            "and PostgreSQL.&lt;/p&gt;"
            "&lt;script&gt;ignored()&lt;/script&gt;"
        ),
        "departments": [
            {
                "name": "Engineering",
            },
        ],
        "offices": [
            {
                "name": "Remote",
                "location": "Worldwide",
            },
        ],
    }


def encode_payload(
    jobs: list[dict[str, object]],
) -> bytes:
    return json.dumps(
        {
            "jobs": jobs,
            "meta": {
                "total": len(jobs),
            },
        }
    ).encode()


def build_client(
    responses: Mapping[
        str,
        tuple[int, bytes],
    ],
) -> httpx.AsyncClient:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        board_token = request.url.path.split("/")[-2]
        status_code, content = responses[board_token]

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
async def test_fetch_page_maps_multiple_boards() -> None:
    first_board = GreenhouseBoard(
        slug="firstcompany",
        company_name="First Company",
        all_jobs_remote=True,
    )
    second_board = GreenhouseBoard(
        slug="secondcompany",
        company_name="Second Company",
        all_jobs_remote=True,
    )

    responses = {
        "firstcompany": (
            200,
            encode_payload(
                [
                    valid_greenhouse_job(
                        job_id=101,
                    ),
                ]
            ),
        ),
        "secondcompany": (
            200,
            encode_payload(
                [
                    valid_greenhouse_job(
                        job_id=202,
                    ),
                ]
            ),
        ),
    }

    async with build_client(responses) as client:
        result = await GreenhouseJobSource(
            client=client,
            boards=(
                first_board,
                second_board,
            ),
        ).fetch_page()

    assert result.page == 1
    assert result.has_next_page is False
    assert result.rejected_count == 0
    assert result.skipped_non_remote_count == 0
    assert len(result.records) == 2

    first_record = result.records[0]
    second_record = result.records[1]

    assert first_record.source_name == "greenhouse"
    assert first_record.source_job_id == ("firstcompany:101")
    assert first_record.company_name == "First Company"
    assert second_record.source_job_id == ("secondcompany:202")
    assert second_record.company_name == ("Second Company")

    assert first_record.location == ("Remote - Europe, Middle East")
    assert first_record.remote_regions == [
        "Europe",
        "Middle East",
    ]
    assert first_record.employment_type == "full_time"
    assert first_record.experience_level == "senior"
    assert first_record.application_url == (first_record.source_url)

    assert "ignored" not in first_record.description
    assert "Python" in first_record.skills
    assert "FastAPI" in first_record.skills
    assert "PostgreSQL" in first_record.skills

    assert first_record.published_at is not None
    assert first_record.published_at.utcoffset() is not None


@pytest.mark.anyio
async def test_non_remote_jobs_are_skipped() -> None:
    board = GreenhouseBoard(
        slug="hybridcompany",
        company_name="Hybrid Company",
        all_jobs_remote=False,
    )

    non_remote_job = valid_greenhouse_job(job_id=301)
    non_remote_job.update(
        {
            "title": "Office Manager",
            "location": {
                "name": "New York City",
            },
            "content": ("&lt;p&gt;Work from our New York office five days per week.&lt;/p&gt;"),
            "offices": [
                {
                    "name": "New York Office",
                    "location": "New York, USA",
                },
            ],
        }
    )

    remote_job = valid_greenhouse_job(job_id=302)

    async with build_client(
        {
            "hybridcompany": (
                200,
                encode_payload(
                    [
                        non_remote_job,
                        remote_job,
                    ]
                ),
            ),
        }
    ) as client:
        result = await GreenhouseJobSource(
            client=client,
            boards=(board,),
        ).fetch_page()

    assert len(result.records) == 1
    assert result.records[0].source_job_id == ("hybridcompany:302")
    assert result.skipped_non_remote_count == 1


@pytest.mark.anyio
async def test_all_remote_board_accepts_local_location() -> None:
    board = GreenhouseBoard(
        slug="remotecompany",
        company_name="Remote Company",
        all_jobs_remote=True,
    )

    job = valid_greenhouse_job(job_id=401)
    job["location"] = {
        "name": "Germany",
    }

    async with build_client(
        {
            "remotecompany": (
                200,
                encode_payload([job]),
            ),
        }
    ) as client:
        result = await GreenhouseJobSource(
            client=client,
            boards=(board,),
        ).fetch_page()

    assert len(result.records) == 1
    assert result.records[0].location == "Germany"
    assert result.records[0].remote_regions == [
        "Germany",
    ]


@pytest.mark.anyio
async def test_invalid_jobs_are_counted() -> None:
    board = GreenhouseBoard(
        slug="example",
        company_name="Example",
        all_jobs_remote=True,
    )

    invalid_job = valid_greenhouse_job()
    invalid_job.pop("title")

    async with build_client(
        {
            "example": (
                200,
                encode_payload(
                    [
                        invalid_job,
                        valid_greenhouse_job(
                            job_id=502,
                        ),
                    ]
                ),
            ),
        }
    ) as client:
        result = await GreenhouseJobSource(
            client=client,
            boards=(board,),
        ).fetch_page()

    assert len(result.records) == 1
    assert result.rejected_count == 1


@pytest.mark.anyio
async def test_invalid_payload_is_rejected() -> None:
    board = GreenhouseBoard(
        slug="example",
        company_name="Example",
        all_jobs_remote=True,
    )

    async with build_client(
        {
            "example": (
                200,
                json.dumps(
                    {
                        "unexpected": [],
                    }
                ).encode(),
            ),
        }
    ) as client:
        with pytest.raises(
            GreenhouseSourceError,
            match="invalid Greenhouse response",
        ):
            await GreenhouseJobSource(
                client=client,
                boards=(board,),
            ).fetch_page()


@pytest.mark.anyio
async def test_http_failure_is_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    board = GreenhouseBoard(
        slug="example",
        company_name="Example",
        all_jobs_remote=True,
    )

    async with build_client(
        {
            "example": (
                503,
                b"",
            ),
        }
    ) as client:
        with pytest.raises(
            GreenhouseSourceError,
            match="Unable to fetch",
        ):
            await GreenhouseJobSource(
                client=client,
                boards=(board,),
            ).fetch_page()


@pytest.mark.anyio
async def test_fetch_page_retries_transient_failure_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    flaky_board = GreenhouseBoard(
        slug="flakycompany",
        company_name="Flaky Company",
        all_jobs_remote=True,
    )
    healthy_board = GreenhouseBoard(
        slug="healthycompany",
        company_name="Healthy Company",
        all_jobs_remote=True,
    )

    call_counts = {
        "flakycompany": 0,
        "healthycompany": 0,
    }

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        board_token = request.url.path.split("/")[-2]
        call_counts[board_token] += 1

        if board_token == "flakycompany" and call_counts[board_token] == 1:
            return httpx.Response(status_code=503, content=b"")

        payload = encode_payload(
            [
                valid_greenhouse_job(
                    job_id=(1 if board_token == "flakycompany" else 2),
                ),
            ]
        )

        return httpx.Response(
            status_code=200,
            content=payload,
            headers={"Content-Type": "application/json"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await GreenhouseJobSource(
            client=client,
            boards=(flaky_board, healthy_board),
        ).fetch_page()

    assert call_counts["flakycompany"] == 2
    assert call_counts["healthycompany"] == 1
    assert len(result.records) == 2


@pytest.mark.anyio
async def test_fetch_page_does_not_retry_non_retryable_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(delay: float) -> None:
        del delay
        raise AssertionError("sleep should not be called for a non-retryable failure")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    call_count = 0

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        del request
        nonlocal call_count
        call_count += 1

        return httpx.Response(status_code=404, content=b"")

    board = GreenhouseBoard(
        slug="example",
        company_name="Example",
        all_jobs_remote=True,
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            GreenhouseSourceError,
            match="Unable to fetch",
        ):
            await GreenhouseJobSource(
                client=client,
                boards=(board,),
            ).fetch_page()

    assert call_count == 1


@pytest.mark.anyio
async def test_fetch_page_raises_after_exhausting_retries(
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

        return httpx.Response(status_code=503, content=b"")

    board = GreenhouseBoard(
        slug="example",
        company_name="Example",
        all_jobs_remote=True,
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            GreenhouseSourceError,
            match="Unable to fetch",
        ) as error_info:
            await GreenhouseJobSource(
                client=client,
                boards=(board,),
            ).fetch_page()

    assert call_count == 3
    assert isinstance(error_info.value.__cause__, httpx.HTTPStatusError)
    assert error_info.value.__cause__.response.status_code == 503


@pytest.mark.anyio
async def test_oversized_response_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.integrations.job_sources.greenhouse.MAX_SOURCE_RESPONSE_BYTES",
        10,
    )

    board = GreenhouseBoard(
        slug="example",
        company_name="Example",
        all_jobs_remote=True,
    )

    async with build_client(
        {
            "example": (
                200,
                b"response larger than ten bytes",
            ),
        }
    ) as client:
        with pytest.raises(
            GreenhouseSourceError,
            match="exceeded the allowed size",
        ):
            await GreenhouseJobSource(
                client=client,
                boards=(board,),
            ).fetch_page()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "page",
    [
        0,
        2,
        100,
    ],
)
async def test_unsupported_pages_are_rejected(
    page: int,
) -> None:
    board = GreenhouseBoard(
        slug="example",
        company_name="Example",
        all_jobs_remote=True,
    )

    source = GreenhouseJobSource(
        boards=(board,),
    )

    with pytest.raises(
        ValueError,
        match="supports only page 1",
    ):
        await source.fetch_page(page=page)


def test_at_least_one_board_is_required() -> None:
    with pytest.raises(
        ValueError,
        match="At least one Greenhouse board",
    ):
        GreenhouseJobSource(boards=())
