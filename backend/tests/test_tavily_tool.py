"""Unit tests for app.tools.tavily_tool (TavilyClient patched)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import get_settings
from app.schemas.common import SentimentLabel
from app.schemas.news import NewsItem
from app.tools.base import InvalidInputError, NoDataError, RateLimitError
from app.tools.tavily_tool import clear_news_cache, search_ticker_news


@pytest.fixture(autouse=True)
def _reset_news_cache():
    """Every test starts with an empty Tavily cache so results don't bleed across tests."""
    clear_news_cache()
    yield
    clear_news_cache()


def _fake_response() -> dict:
    return {
        "results": [
            {
                "title": "Apple beats Q1 expectations",
                "url": "https://www.reuters.com/markets/aapl-beats-q1",
                "content": "Apple Inc. reported stronger-than-expected quarterly earnings...",
                "score": 0.91,
                "published_date": "2026-04-10",
            },
            {
                "title": "Apple faces new antitrust lawsuit",
                "url": "https://www.bloomberg.com/news/apple-lawsuit",
                "content": "A coalition of developers filed a new complaint...",
                "score": 0.73,
                "published_date": "2026-04-09T14:02:00Z",
            },
            # Invalid row: missing url - should be skipped, not crash
            {"title": "No URL", "content": "should be skipped"},
        ]
    }


def test_search_ticker_news_happy_uses_configured_defaults():
    """With no explicit kwargs, the tool reads defaults from Settings."""
    client = MagicMock()
    client.search.return_value = _fake_response()
    settings = get_settings()

    with patch("app.tools.tavily_tool.TavilyClient", return_value=client):
        items = search_ticker_news("AAPL", company_name="Apple Inc.")

    assert len(items) == 2
    assert all(isinstance(i, NewsItem) for i in items)
    assert items[0].source == "reuters.com"
    assert items[0].sentiment == SentimentLabel.NEUTRAL
    assert items[0].relevance_score == 0.91
    assert items[1].published_at is not None
    assert items[1].published_at.tzinfo is not None

    called = client.search.call_args.kwargs
    assert called["topic"] == "news"
    assert called["days"] == settings.tavily_days_back
    assert called["max_results"] == settings.tavily_max_results
    assert called["search_depth"] == settings.tavily_search_depth


def test_search_ticker_news_explicit_kwargs_override_settings():
    client = MagicMock()
    client.search.return_value = _fake_response()

    with patch("app.tools.tavily_tool.TavilyClient", return_value=client):
        search_ticker_news(
            "AAPL", max_results=3, days_back=2, search_depth="advanced"
        )

    called = client.search.call_args.kwargs
    assert called["days"] == 2
    assert called["max_results"] == 3
    assert called["search_depth"] == "advanced"


def test_search_ticker_news_rejects_bad_bounds():
    with pytest.raises(InvalidInputError):
        search_ticker_news("AAPL", max_results=0)
    with pytest.raises(InvalidInputError):
        search_ticker_news("AAPL", days_back=500)
    with pytest.raises(InvalidInputError):
        search_ticker_news("AAPL", search_depth="turbo")


def test_search_ticker_news_no_results():
    client = MagicMock()
    client.search.return_value = {"results": []}
    with patch("app.tools.tavily_tool.TavilyClient", return_value=client):
        with pytest.raises(NoDataError):
            search_ticker_news("AAPL")


def test_search_ticker_news_rate_limit_maps():
    client = MagicMock()
    client.search.side_effect = RuntimeError("HTTP 429 rate limit exceeded")
    with patch("app.tools.tavily_tool.TavilyClient", return_value=client):
        with pytest.raises(RateLimitError):
            search_ticker_news("AAPL")


# ---------------------------------------------------------------------------
# TTL cache
# ---------------------------------------------------------------------------


def test_search_ticker_news_caches_results_within_ttl(monkeypatch):
    """Second call with identical args must NOT hit Tavily again."""
    settings = get_settings()
    monkeypatch.setattr(settings, "tavily_cache_ttl_seconds", 300)

    client = MagicMock()
    client.search.return_value = _fake_response()

    with patch("app.tools.tavily_tool.TavilyClient", return_value=client):
        first = search_ticker_news("AAPL", company_name="Apple Inc.")
        second = search_ticker_news("AAPL", company_name="Apple Inc.")

    assert client.search.call_count == 1
    assert len(first) == len(second) == 2
    # Defensive-copy guarantee: mutating the returned list doesn't corrupt cache.
    second.clear()
    with patch("app.tools.tavily_tool.TavilyClient", return_value=client):
        third = search_ticker_news("AAPL", company_name="Apple Inc.")
    assert len(third) == 2
    assert client.search.call_count == 1  # still cached


def test_search_ticker_news_cache_key_differentiates_params(monkeypatch):
    """Different params => different cache keys => separate upstream calls."""
    settings = get_settings()
    monkeypatch.setattr(settings, "tavily_cache_ttl_seconds", 300)

    client = MagicMock()
    client.search.return_value = _fake_response()

    with patch("app.tools.tavily_tool.TavilyClient", return_value=client):
        search_ticker_news("AAPL", max_results=5, days_back=7)
        search_ticker_news("AAPL", max_results=3, days_back=7)  # different max
        search_ticker_news("MSFT", max_results=5, days_back=7)  # different ticker

    assert client.search.call_count == 3


def test_search_ticker_news_cache_disabled_when_ttl_zero(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tavily_cache_ttl_seconds", 0)

    client = MagicMock()
    client.search.return_value = _fake_response()

    with patch("app.tools.tavily_tool.TavilyClient", return_value=client):
        search_ticker_news("AAPL")
        search_ticker_news("AAPL")

    assert client.search.call_count == 2


def test_search_ticker_news_cache_respects_expiry(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tavily_cache_ttl_seconds", 1)

    client = MagicMock()
    client.search.return_value = _fake_response()

    # Control the clock: make the second call appear 60s later.
    fake_now = {"t": 1000.0}

    def _monotonic():
        return fake_now["t"]

    monkeypatch.setattr("app.tools.tavily_tool.time.monotonic", _monotonic)

    with patch("app.tools.tavily_tool.TavilyClient", return_value=client):
        search_ticker_news("AAPL")
        fake_now["t"] += 60  # TTL (1s) long expired
        search_ticker_news("AAPL")

    assert client.search.call_count == 2
