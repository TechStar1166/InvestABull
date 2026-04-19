"""External data tool wrappers.

Each tool exposes a small, strictly-typed function interface. Tools return
Pydantic models (or lists of them) from ``app.schemas``; they NEVER return
free-form strings. Errors are surfaced as ``ToolError`` subclasses defined in
``app.tools.base``.
"""

from app.tools.base import (
    InvalidInputError,
    NoDataError,
    RateLimitError,
    ToolError,
    UpstreamAPIError,
    validate_ticker,
    with_retries,
)

__all__ = [
    "InvalidInputError",
    "NoDataError",
    "RateLimitError",
    "ToolError",
    "UpstreamAPIError",
    "validate_ticker",
    "with_retries",
]
