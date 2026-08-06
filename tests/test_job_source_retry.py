import httpx
import pytest

from app.integrations.job_sources.base import JobSourceError
from app.integrations.job_sources.retry import (
    is_retryable_httpx_error,
    retry_async,
)


class _RetryableStubError(Exception):
    """A stand-in for a retryable failure in isolated retry_async tests."""


class _NonRetryableStubError(Exception):
    """A stand-in for a non-retryable failure in isolated retry_async tests."""


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _is_retryable_stub(error: Exception) -> bool:
    return isinstance(error, _RetryableStubError)


def _fake_sleep(recorded_delays: list[float]) -> object:
    async def sleep(delay: float) -> None:
        recorded_delays.append(delay)

    return sleep


@pytest.mark.anyio
async def test_retry_async_returns_result_on_first_success() -> None:
    call_count = 0

    async def operation() -> str:
        nonlocal call_count
        call_count += 1
        return "ok"

    recorded_delays: list[float] = []

    result = await retry_async(
        operation,
        is_retryable=_is_retryable_stub,
        sleep=_fake_sleep(recorded_delays),
    )

    assert result == "ok"
    assert call_count == 1
    assert recorded_delays == []


@pytest.mark.anyio
async def test_retry_async_retries_until_success() -> None:
    call_count = 0

    async def operation() -> str:
        nonlocal call_count
        call_count += 1

        if call_count < 3:
            raise _RetryableStubError("transient")

        return "ok"

    recorded_delays: list[float] = []

    result = await retry_async(
        operation,
        is_retryable=_is_retryable_stub,
        sleep=_fake_sleep(recorded_delays),
    )

    assert result == "ok"
    assert call_count == 3
    assert len(recorded_delays) == 2


@pytest.mark.anyio
async def test_retry_async_stops_immediately_when_not_retryable() -> None:
    call_count = 0

    async def operation() -> str:
        nonlocal call_count
        call_count += 1
        raise _NonRetryableStubError("permanent")

    recorded_delays: list[float] = []

    with pytest.raises(_NonRetryableStubError):
        await retry_async(
            operation,
            is_retryable=_is_retryable_stub,
            sleep=_fake_sleep(recorded_delays),
        )

    assert call_count == 1
    assert recorded_delays == []


@pytest.mark.anyio
async def test_retry_async_raises_last_exception_after_exhausting_attempts() -> None:
    call_count = 0
    raised_errors: list[Exception] = []

    async def operation() -> str:
        nonlocal call_count
        call_count += 1
        error = _RetryableStubError(f"attempt {call_count}")
        raised_errors.append(error)
        raise error

    recorded_delays: list[float] = []

    with pytest.raises(_RetryableStubError) as error_info:
        await retry_async(
            operation,
            is_retryable=_is_retryable_stub,
            max_attempts=3,
            sleep=_fake_sleep(recorded_delays),
        )

    assert call_count == 3
    assert error_info.value is raised_errors[-1]


@pytest.mark.anyio
async def test_retry_async_preserves_cause_chain_end_to_end() -> None:
    async def operation() -> str:
        raise httpx.ConnectError("connection refused")

    recorded_delays: list[float] = []

    class _WrappedError(JobSourceError):
        """Mirrors the connector's own wrap-and-raise-from pattern."""

    with pytest.raises(_WrappedError) as error_info:
        try:
            await retry_async(
                operation,
                is_retryable=is_retryable_httpx_error,
                max_attempts=2,
                sleep=_fake_sleep(recorded_delays),
            )
        except httpx.HTTPError as error:
            raise _WrappedError("Unable to fetch.") from error

    assert isinstance(error_info.value.__cause__, httpx.ConnectError)


@pytest.mark.anyio
async def test_retry_async_computes_exponential_backoff_delays() -> None:
    async def operation() -> str:
        raise _RetryableStubError("transient")

    recorded_delays: list[float] = []

    with pytest.raises(_RetryableStubError):
        await retry_async(
            operation,
            is_retryable=_is_retryable_stub,
            max_attempts=3,
            base_delay=0.5,
            multiplier=2.0,
            sleep=_fake_sleep(recorded_delays),
        )

    assert recorded_delays == [0.5, 1.0]


@pytest.mark.anyio
async def test_retry_async_respects_max_delay_cap() -> None:
    async def operation() -> str:
        raise _RetryableStubError("transient")

    recorded_delays: list[float] = []

    with pytest.raises(_RetryableStubError):
        await retry_async(
            operation,
            is_retryable=_is_retryable_stub,
            max_attempts=4,
            base_delay=1.0,
            multiplier=10.0,
            max_delay=5.0,
            sleep=_fake_sleep(recorded_delays),
        )

    assert recorded_delays == [1.0, 5.0, 5.0]


@pytest.mark.anyio
async def test_retry_async_does_not_sleep_after_final_attempt() -> None:
    async def operation() -> str:
        raise _RetryableStubError("transient")

    recorded_delays: list[float] = []

    with pytest.raises(_RetryableStubError):
        await retry_async(
            operation,
            is_retryable=_is_retryable_stub,
            max_attempts=5,
            sleep=_fake_sleep(recorded_delays),
        )

    assert len(recorded_delays) == 4


@pytest.mark.anyio
@pytest.mark.parametrize(
    "transport_error",
    [
        httpx.ConnectError("boom"),
        httpx.ConnectTimeout("boom"),
        httpx.ReadTimeout("boom"),
        httpx.WriteTimeout("boom"),
        httpx.PoolTimeout("boom"),
    ],
)
async def test_is_retryable_true_for_transport_errors(
    transport_error: httpx.TransportError,
) -> None:
    assert is_retryable_httpx_error(transport_error) is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status_code",
    [429, 500, 503],
)
async def test_is_retryable_true_for_429_and_5xx(
    status_code: int,
) -> None:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code, request=request)
    error = httpx.HTTPStatusError(
        "failure",
        request=request,
        response=response,
    )

    assert is_retryable_httpx_error(error) is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status_code",
    [400, 401, 403, 404],
)
async def test_is_retryable_false_for_other_4xx(
    status_code: int,
) -> None:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code, request=request)
    error = httpx.HTTPStatusError(
        "failure",
        request=request,
        response=response,
    )

    assert is_retryable_httpx_error(error) is False


@pytest.mark.anyio
async def test_is_retryable_false_for_non_httpx_exceptions() -> None:
    assert is_retryable_httpx_error(JobSourceError("bad payload")) is False
    assert is_retryable_httpx_error(ValueError("bad page")) is False
