"""Tavily search tool implementation.

Returns normalized :class:`~app.schemas.news.NewsItem` objects. Sentiment is
deliberately left ``neutral`` at the tool layer - classification is the News
agent's job so we never mix retrieval with reasoning.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from tavily import TavilyClient

from app.config import get_settings
from app.schemas.common import SentimentLabel
from app.schemas.news import NewsItem
from app.tools.base import (
    InvalidInputError,
    NoDataError,
    RateLimitError,
    UpstreamAPIError,
    validate_ticker,
    with_retries,
)

logger = logging.getLogger(__name__)

_SNIPPET_MAX = 1_500  # keep in lockstep with NewsItem.snippet max_length


def _parse_published(v: Any) -> datetime | None:
    """Best-effort conversion of a Tavily published_date field to UTC datetime."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(int(v), tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(v, str):
        s = v.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        try:
            return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _host_of(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    return host.removeprefix("www.") or url


def _truncate(s: str | None, n: int) -> str | None:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    return s if len(s) <= n else s[: n - 1].rstrip() + "\u2026"


@with_retries
def search_ticker_news(
    ticker: str,
    *,
    company_name: str | None = None,
    max_results: int = 10,
    days_back: int = 14,
) -> list[NewsItem]:
    """Return recent news articles relevant to ``ticker``.

    Raises
    ------
    InvalidInputError
        If ``ticker``, ``max_results``, or ``days_back`` are out of range.
    RateLimitError
        If Tavily throttles the request (retryable).
    UpstreamAPIError
        For other Tavily failures or missing API key.
    NoDataError
        If no articles match the query.
    """
    symbol = validate_ticker(ticker)
    if not (1 <= int(max_results) <= 50):
        raise InvalidInputError("max_results must be in [1, 50]")
    if not (1 <= int(days_back) <= 90):
        raise InvalidInputError("days_back must be in [1, 90]")

    settings = get_settings()
    if not settings.tavily_api_key:
        raise UpstreamAPIError("TAVILY_API_KEY is not configured")

    client = TavilyClient(api_key=settings.tavily_api_key)

    q_parts = [f"{symbol} stock"]
    if company_name:
        q_parts.append(company_name)
    q_parts.append("earnings OR guidance OR analyst OR SEC OR lawsuit OR product")
    query = " ".join(q_parts)

    try:
        resp = client.search(
            query=query,
            search_depth="advanced",
            topic="news",
            days=int(days_back),
            max_results=int(max_results),
        )
    except Exception as e:
        msg = str(e).lower()
        if "rate" in msg or "429" in msg or "quota" in msg:
            raise RateLimitError(f"Tavily rate-limited: {e}") from e
        raise UpstreamAPIError(f"Tavily search failed: {e}") from e

    results = (resp or {}).get("results") or []
    items: list[NewsItem] = []
    for r in results:
        url = r.get("url")
        title = r.get("title")
        if not url or not title:
            continue
        try:
            item = NewsItem(
                title=str(title).strip()[:300],
                url=url,
                source=_host_of(url),
                published_at=_parse_published(
                    r.get("published_date") or r.get("published_at")
                ),
                snippet=_truncate(r.get("content"), _SNIPPET_MAX),
                sentiment=SentimentLabel.NEUTRAL,
                sentiment_score=None,
                relevance_score=r.get("score"),
            )
        except Exception as e:  # pydantic validation of a bad result row
            logger.debug("Skipping invalid Tavily result for %s: %s", symbol, e)
            continue
        items.append(item)

    if not items:
        raise NoDataError(f"Tavily returned no articles for {symbol}")
    return items
