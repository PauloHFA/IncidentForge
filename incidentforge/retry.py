"""Retry logic with exponential backoff for IncidentForge."""

from __future__ import annotations

import logging
import random
from typing import Callable, TypeVar

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .client import LLMResponse

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryableError(Exception):
    """Base class for retryable errors."""

    def __init__(self, message: str, status_code: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class RateLimitError(RetryableError):
    """Rate limit error (HTTP 429)."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message, status_code=429, retry_after=retry_after)


class ServerError(RetryableError):
    """Server error (HTTP 5xx)."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message, status_code=status_code)


class TimeoutError(RetryableError):
    """Timeout error."""

    def __init__(self, message: str):
        super().__init__(message, status_code=408)


class NonRetryableError(Exception):
    """Non-retryable error (e.g., 401, 403, 400)."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def is_retryable_exception(exc: BaseException) -> bool:
    """Check if exception is retryable."""
    if isinstance(exc, RetryableError):
        return True
    if isinstance(exc, NonRetryableError):
        return False
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    # Check for HTTP status codes in httpx exceptions
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or 500 <= status < 600
    return False


def extract_retry_after(exc: BaseException) -> float | None:
    """Extract Retry-After header from exception."""
    if isinstance(exc, RateLimitError) and exc.retry_after is not None:
        return exc.retry_after
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                # Could be a date, ignore for now
                pass
    return None


def before_sleep_log_retry(retry_state: RetryCallState) -> None:
    """Log before sleep with retry info."""
    if retry_state.outcome and retry_state.outcome.exception():
        exc = retry_state.outcome.exception()
        retry_after = extract_retry_after(exc)
        attempt = retry_state.attempt_number
        if retry_after:
            logger.warning(
                f"Retry attempt {attempt}: {exc}. "
                f"Waiting {retry_after:.1f}s (Retry-After header)"
            )
        else:
            logger.warning(
                f"Retry attempt {attempt}: {exc}. "
                f"Waiting with exponential backoff"
            )


def create_retry_policy(
    max_attempts: int = 3,
    base_wait: float = 1.0,
    max_wait: float = 60.0,
    jitter: float = 0.5,
) -> AsyncRetrying:
    """
    Create retry policy with exponential backoff and jitter.

    Args:
        max_attempts: Maximum number of attempts (including first).
        base_wait: Base wait time in seconds.
        max_wait: Maximum wait time in seconds.
        jitter: Jitter factor (0-1).

    Returns:
        Configured AsyncRetrying instance.
    """
    return AsyncRetrying(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(
            initial=base_wait,
            max=max_wait,
            jitter=jitter,
        ),
        before_sleep=before_sleep_log_retry,
        reraise=True,
    )


async def with_retry(
    func: Callable[..., T],
    *args,
    max_attempts: int = 3,
    base_wait: float = 1.0,
    max_wait: float = 60.0,
    jitter: float = 0.5,
    **kwargs
) -> T:
    """
    Execute function with retry policy.

    Args:
        func: Async function to execute.
        *args: Positional arguments for func.
        max_attempts: Maximum number of attempts.
        base_wait: Base wait time in seconds.
        max_wait: Maximum wait time in seconds.
        jitter: Jitter factor.
        **kwargs: Keyword arguments for func.

    Returns:
        Result of func.

    Raises:
        Last exception if all retries exhausted.
    """
    retryer = create_retry_policy(
        max_attempts=max_attempts,
        base_wait=base_wait,
        max_wait=max_wait,
        jitter=jitter,
    )
    return await retryer(func, *args, **kwargs)


def classify_http_error(status_code: int, message: str, headers: dict | None = None) -> Exception:
    """
    Classify HTTP error into appropriate exception type.

    Args:
        status_code: HTTP status code.
        message: Error message.
        headers: Response headers.

    Returns:
        Appropriate exception instance.
    """
    headers = headers or {}
    retry_after = headers.get("Retry-After")

    if status_code == 429:
        retry_after_float = None
        if retry_after:
            try:
                retry_after_float = float(retry_after)
            except ValueError:
                pass
        return RateLimitError(message, retry_after=retry_after_float)

    if 500 <= status_code < 600:
        return ServerError(message, status_code)

    if status_code == 408:
        return TimeoutError(message)

    # Non-retryable errors
    return NonRetryableError(message, status_code)


async def handle_llm_response(response: LLMResponse) -> LLMResponse:
    """
    Handle LLM response, raising appropriate exceptions for errors.

    This is a placeholder for handling errors from the LLM response itself
    (e.g., if the API returns an error in the response body).
    """
    # The actual HTTP errors are handled at the client level
    # This function can be extended to handle response-level errors
    return response


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_wait: float = 1.0,
        max_wait: float = 60.0,
        jitter: float = 0.5,
        max_validation_retries: int = 2,
    ):
        self.max_attempts = max_attempts
        self.base_wait = base_wait
        self.max_wait = max_wait
        self.jitter = jitter
        self.max_validation_retries = max_validation_retries

    def create_retryer(self) -> AsyncRetrying:
        """Create retryer with this config."""
        return create_retry_policy(
            max_attempts=self.max_attempts,
            base_wait=self.base_wait,
            max_wait=self.max_wait,
            jitter=self.jitter,
        )


DEFAULT_RETRY_CONFIG = RetryConfig()


if __name__ == "__main__":
    import asyncio

    async def test_retry():
        """Test retry logic."""
        attempt = 0

        async def failing_func():
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise RateLimitError("Rate limited", retry_after=0.1)
            return "success"

        try:
            result = await with_retry(failing_func, max_attempts=5, base_wait=0.1, max_wait=1.0)
            print(f"Result: {result}")
        except Exception as e:
            print(f"Failed after retries: {e}")

    asyncio.run(test_retry())