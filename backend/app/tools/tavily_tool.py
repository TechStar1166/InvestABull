"""Tavily search tool implementation.

Returns normalized :class:`~app.schemas.news.NewsItem` objects. Sentiment is
deliberately left ``neutral`` at the tool layer - classification is the News
agent's job so we never mix retrieval with reasoning.
"""

from __future__ import annotations

import logging
import threading
import time
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


# ---------------------------------------------------------------------------
# In-memory TTL cache for Tavily results
#
# News doesn't need to be re-fetched on every /research call for the same
# ticker: Tavily charges per query and adds multi-second latency even for
# repeat hits. A short TTL per (ticker, params) key wipes the bulk of that
# cost when users retry quickly or when multiple agents / workers hit the
# same ticker in a short window.
#
# Safe for our threaded pipeline: a single ``threading.Lock`` guards the
# dict. For multi-worker deploys (gunicorn, uvicorn --workers >1) this only
# dedupes within a single process; swap for Redis if you need shared state.
# ---------------------------------------------------------------------------

_CacheKey = tuple[str, int, int, str, str]
_CacheEntry = tuple[float, list[NewsItem]]

_news_cache: dict[_CacheKey, _CacheEntry] = {}
_news_cache_lock = threading.Lock()


def _cache_get(key: _CacheKey, ttl: int) -> list[NewsItem] | None:
    if ttl <= 0:
        return None
    now = time.monotonic()
    with _news_cache_lock:
        entry = _news_cache.get(key)
        if not entry:
            return None
        ts, items = entry
        if now - ts > ttl:
            _news_cache.pop(key, None)
            return None
        # Shallow-copy list so callers mutating it don't corrupt the cache.
        return list(items)


def _cache_put(key: _CacheKey, items: list[NewsItem]) -> None:
    with _news_cache_lock:
        _news_cache[key] = (time.monotonic(), list(items))


def clear_news_cache() -> None:
    """Drop all cached Tavily results. Exposed for tests and manual refreshes."""
    with _news_cache_lock:
        _news_cache.clear()


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
    max_results: int | None = None,
    days_back: int | None = None,
    search_depth: str | None = None,
) -> list[NewsItem]:
    """Return recent news articles relevant to ``ticker``.

    All tuning knobs (``max_results``, ``days_back``, ``search_depth``) default
    to the values in :class:`app.config.Settings` so operators can retune news
    speed without code changes. Call with explicit kwargs to override for a
    single call.

    Results are cached in-process for ``TAVILY_CACHE_TTL_SECONDS`` (0 disables
    caching) keyed on ``(ticker, days_back, max_results, company_name,
    search_depth)`` so repeat requests within the TTL skip the network call.

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
    settings = get_settings()

    symbol = validate_ticker(ticker)
    effective_max = int(max_results if max_results is not None else settings.tavily_max_results)
    effective_days = int(days_back if days_back is not None else settings.tavily_days_back)
    effective_depth = (search_depth or settings.tavily_search_depth or "basic").lower()
    if effective_depth not in {"basic", "advanced"}:
        raise InvalidInputError("search_depth must be 'basic' or 'advanced'")
    if not (1 <= effective_max <= 50):
        raise InvalidInputError("max_results must be in [1, 50]")
    if not (1 <= effective_days <= 90):
        raise InvalidInputError("days_back must be in [1, 90]")

    if not settings.tavily_api_key:
        raise UpstreamAPIError("TAVILY_API_KEY is not configured")

    cache_key: _CacheKey = (
        symbol,
        effective_days,
        effective_max,
        (company_name or "").strip().lower(),
        effective_depth,
    )
    cached = _cache_get(cache_key, settings.tavily_cache_ttl_seconds)
    if cached is not None:
        logger.debug("news cache hit for %s", symbol)
        return cached

    client = TavilyClient(api_key=settings.tavily_api_key)

    q_parts = [f"{symbol} stock"]
    if company_name:
        q_parts.append(company_name)
    q_parts.append("earnings OR guidance OR analyst OR SEC OR lawsuit OR product")
    query = " ".join(q_parts)

    try:
        resp = client.search(
            query=query,
            search_depth=effective_depth,
            topic="news",
            days=effective_days,
            max_results=effective_max,
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

    _cache_put(cache_key, items)
    return items
