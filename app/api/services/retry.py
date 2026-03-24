"""
app/api/services/retry.py
Async retry utility with exponential backoff.

Used by pipeline nodes when calling Claude API or other external services.
Retries up to max_attempts with jitter to avoid thundering herd on rate limits.

TruncatedOutputError is raised by layer_generator when Claude's output was cut
off before the file was complete. Passing it in no_retry_on causes retry_async
to re-raise it immediately so the caller can route to split generation rather
than wasting tokens on an identical prompt.
"""

import asyncio
import random
from typing import Any, Callable, TypeVar

from loguru import logger

T = TypeVar("T")


class TruncatedOutputError(Exception):
    """
    Raised when Claude's output was cut off before the file was complete.

    Carries the partial content so callers can use it as context for Part 2
    of a split-generation fallback.

    Never retried with the same prompt — retry_async re-raises it immediately
    when it appears in no_retry_on. The caller is responsible for routing to
    _generate_file_split instead.
    """

    def __init__(self, message: str, partial_content: str = "") -> None:
        super().__init__(message)
        self.partial_content = partial_content


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
    no_retry_on: tuple = (),
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
        exceptions:   Exception types that trigger a retry (default all).
        no_retry_on:  Exception types that are re-raised immediately without
                      any retry or backoff. Use for TruncatedOutputError so
                      split generation handles it rather than a plain retry.
        label:        Human-readable label for log messages.
        **kwargs:     Keyword args passed to func.

    Returns:
        Result of func on success.

    Raises:
        Any exception in no_retry_on: immediately, no retry.
        The last exception if all retryable attempts fail.
    """
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await func(*args, **kwargs)
        except BaseException as exc:
            # no_retry_on: re-raise immediately — caller handles these specially
            if no_retry_on and isinstance(exc, no_retry_on):
                logger.debug(
                    f"[retry] {label} raised {type(exc).__name__} — "
                    f"re-raising immediately (no_retry_on)"
                )
                raise

            # Only retry on the specified exception types
            if not isinstance(exc, exceptions):
                raise

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
