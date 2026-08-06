import asyncio
from collections.abc import Awaitable, Callable

import httpx


def is_retryable_httpx_error(error: Exception) -> bool:
    if isinstance(error, httpx.TransportError):
        return True

    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code

        return status_code == 429 or status_code >= 500

    return False


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    is_retryable: Callable[[Exception], bool],
    max_attempts: int = 3,
    base_delay: float = 0.5,
    multiplier: float = 2.0,
    max_delay: float = 8.0,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T:
    delay = base_delay

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except Exception as error:
            if attempt == max_attempts or not is_retryable(error):
                raise

            sleep_fn = sleep or asyncio.sleep
            await sleep_fn(delay)
            delay = min(delay * multiplier, max_delay)

    raise AssertionError("unreachable")
