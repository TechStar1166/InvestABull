"""Shared primitives for every tool wrapper: error types, retries, validation.

Rationale
---------
Keeping these utilities in one place guarantees that:

* Every tool raises a consistent, catchable exception hierarchy.
* Retry / backoff policy is identical across providers.
* Input validation (tickers, dates, series ids) lives next to the errors it
  can raise, so callers never have to import from multiple modules.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Base class for every error raised by tool wrappers."""


class InvalidInputError(ToolError):
    """The caller passed invalid arguments (bad ticker, unknown series, ...)."""


class UpstreamAPIError(ToolError):
    """An external provider returned an error we cannot recover from."""


class RateLimitError(UpstreamAPIError):
    """We were throttled by the upstream provider. Retryable."""


class NoDataError(ToolError):
    """The provider responded successfully but returned no usable data."""


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def validate_ticker(ticker: str) -> str:
    """Normalize and validate a stock ticker.

    Returns
    -------
    str
        The upper-cased ticker.

    Raises
    ------
    InvalidInputError
        If ``ticker`` is empty or contains unsupported characters.
    """
    if not isinstance(ticker, str):
        raise InvalidInputError(f"ticker must be a str, got {type(ticker).__name__}")
    candidate = ticker.strip().upper()
    if not _TICKER_PATTERN.match(candidate):
        raise InvalidInputError(
            f"ticker {ticker!r} is not a valid symbol "
            "(expected 1-10 chars, A-Z/0-9/./-, starting with a letter)"
        )
    return candidate


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------


def _log_retry(state: RetryCallState) -> None:
    exc = state.outcome.exception() if state.outcome else None
    logger.warning(
        "tool retry",
        extra={
            "attempt": state.attempt_number,
            "fn": state.fn.__qualname__ if state.fn else "<unknown>",
            "error": repr(exc),
        },
    )


def with_retries(fn: Callable[..., T]) -> Callable[..., T]:
    """Decorate a tool call with exponential-backoff retries.

    Only retryable errors (``RateLimitError`` and generic ``UpstreamAPIError``)
    are retried; ``InvalidInputError`` and ``NoDataError`` propagate
    immediately since retrying them would never help.
    """
    settings = get_settings()
    return retry(  # type: ignore[return-value]
        retry=retry_if_exception_type((RateLimitError, UpstreamAPIError)),
        stop=stop_after_attempt(max(1, settings.http_max_retries)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
        before_sleep=_log_retry,
        reraise=True,
    )(fn)
