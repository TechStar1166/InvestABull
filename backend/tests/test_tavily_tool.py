"""Unit tests for app.tools.tavily_tool (TavilyClient patched)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.common import SentimentLabel
from app.schemas.news import NewsItem
from app.tools.base import InvalidInputError, NoDataError, RateLimitError
from app.tools.tavily_tool import search_ticker_news


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


def test_search_ticker_news_happy():
    client = MagicMock()
    client.search.return_value = _fake_response()

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
    assert called["days"] == 14
    assert called["max_results"] == 10


def test_search_ticker_news_rejects_bad_bounds():
    with pytest.raises(InvalidInputError):
        search_ticker_news("AAPL", max_results=0)
    with pytest.raises(InvalidInputError):
        search_ticker_news("AAPL", days_back=500)


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
