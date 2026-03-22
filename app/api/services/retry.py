"""
app/api/services/retry.py
Async retry utility with exponential backoff.

Used by pipeline nodes when calling Claude API or other external services.
Retries up to max_attempts with jitter to avoid thundering herd on rate limits.
"""

import asyncio
import random
from typing import Any, Callable, TypeVar

from loguru import logger

T = TypeVar("T")


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
    label: str = "operation",
    **kwargs: Any,
) -> Any:
    """
    Retry an async callable with exponential backoff and jitter.

    Args:
        func:         Async callable to retry.
        *args:        Positional args passed to func.
        max_attempts: Maximum number of attempts (default 3).
        base_delay:   Initial backoff delay in seconds (default 2.0).
        max_delay:    Maximum backoff delay in seconds (default 30.0).
        exceptions:   Exception types that trigger a retry.
        label:        Human-readable label for log messages.
        **kwargs:     Keyword args passed to func.

    Returns:
        Result of func on success.

    Raises:
        The last exception if all attempts fail.
    """
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as exc:
            last_exc = exc
            if attempt == max_attempts:
                logger.error(
                    f"[retry] {label} failed after {max_attempts} attempts: {exc}"
                )
                break

            # Exponential backoff with ±25% jitter
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            delay = delay * (0.75 + random.random() * 0.5)
            logger.warning(
                f"[retry] {label} attempt {attempt}/{max_attempts} failed: {exc}. "
                f"Retrying in {delay:.1f}s..."
            )
            await asyncio.sleep(delay)

    raise last_exc
