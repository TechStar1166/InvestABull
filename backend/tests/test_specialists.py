"""End-to-end tests for specialist runners using a stub LLM."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.agents.parsers import AgentOutputError
from app.agents.specialists import (
    run_filings_specialist,
    run_macro_specialist,
    run_news_specialist,
    run_price_specialist,
)
from app.rag.retrieval import RetrievedChunk
from app.schemas.common import AgentName, SentimentLabel, SourceCitation, TrendDirection
from app.schemas.macro import MacroIndicator
from app.schemas.news import NewsItem
from app.schemas.price import PriceMetrics, ReturnsBundle


# ---------------------------------------------------------------------------
# Stub LLM
# ---------------------------------------------------------------------------


class StubLLM:
    """Deterministic LLM stand-in. Either returns a canned string or calls a fn."""

    def __init__(self, response, model_name: str = "stub-gemini"):
        self.response = response
        self.model_name = model_name
        self.calls: list[dict] = []

    def generate(self, *, system: str, user: str, json_mode: bool = True) -> str:
        self.calls.append({"system": system, "user": user, "json_mode": json_mode})
        if callable(self.response):
            return self.response(self.calls[-1])
        return self.response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _price_metrics() -> PriceMetrics:
    return PriceMetrics(
        ticker="AAPL",
        as_of=_now(),
        currency="USD",
        current_price=210.0,
        previous_close=208.0,
        day_change_pct=0.0096,
        week_52_high=220.0,
        week_52_low=150.0,
        market_cap=3_000_000_000_000,
        pe_ttm=30.0,
        pe_forward=24.0,
        eps_ttm=6.5,
        dividend_yield=0.004,
        beta=1.2,
        avg_volume_30d=50_000_000,
        volatility_30d=0.28,
        moving_avg_50d=205.0,
        moving_avg_200d=190.0,
        returns=ReturnsBundle(
            one_month=0.05, three_month=0.1, six_month=0.2, ytd=0.12, one_year=0.18
        ),
    )


def _news_items() -> list[NewsItem]:
    return [
        NewsItem(
            title="Apple beats Q1 estimates",
            url="https://www.reuters.com/aapl-beat",
            source="reuters.com",
            sentiment=SentimentLabel.NEUTRAL,
            sentiment_score=None,
            relevance_score=0.9,
        ),
        NewsItem(
            title="Apple sued over App Store practices",
            url="https://www.bloomberg.com/aapl-sued",
            source="bloomberg.com",
            sentiment=SentimentLabel.NEUTRAL,
            sentiment_score=None,
            relevance_score=0.7,
        ),
    ]


def _macro_indicators() -> list[MacroIndicator]:
    from datetime import date

    citation = SourceCitation(
        source_name="FRED: CPIAUCSL",
        url="https://fred.stlouisfed.org/series/CPIAUCSL",
        identifier="CPIAUCSL",
        snippet="CPI All Urban Consumers",
        retrieved_at=_now(),
    )
    return [
        MacroIndicator(
            series_id="CPIAUCSL",
            name="CPI All Urban Consumers",
            unit="Index 1982-1984=100",
            frequency="Monthly",
            latest_value=312.5,
            latest_date=date(2026, 3, 1),
            prior_value=311.8,
            prior_date=date(2026, 2, 1),
            yoy_change=0.029,
            trend=TrendDirection.UP,
            citation=citation,
        )
    ]


def _retrieved_chunks() -> list[RetrievedChunk]:
    citation = SourceCitation(
        source_name="SEC 10-K AAPL | 2024-09-28 | risk_factors",
        url="https://www.sec.gov/demo.htm",
        identifier="0000320193-24-000123",
        snippet="Supply chain concentration risk.",
        retrieved_at=_now(),
    )
    return [
        RetrievedChunk(
            text="Our supply chain is concentrated in Asia, exposing us to disruptions.",
            score=0.91,
            chunk_id="0000320193-24-000123:risk_factors:0",
            section="risk_factors",
            accession_number="0000320193-24-000123",
            ticker="AAPL",
            citation=citation,
        ),
    ]


# ---------------------------------------------------------------------------
# Canned LLM responses per agent
# ---------------------------------------------------------------------------


def _price_response() -> str:
    metrics = _price_metrics().model_dump(mode="json")
    payload = {
        "agent_name": "price",
        "ticker": "AAPL",
        "as_of_date": _now_iso(),
        "status": "ok",
        "summary": "Apple trades above its 200-day MA with moderate realized vol.",
        "bullet_points": [
            "Trades 10% above 200-day MA.",
            "PE_ttm 30 vs PE_fwd 24 implies ~20% earnings growth priced in.",
        ],
        "findings": metrics,
        "risks": [
            {
                "category": "volatility",
                "title": "Elevated realized volatility",
                "description": "30d realized vol 28% exceeds typical large-cap baseline (~15%).",
                "severity": "medium",
                "source_section": None,
                "citation": {
                    "source_name": "yfinance",
                    "url": None,
                    "identifier": "AAPL",
                    "snippet": None,
                    "retrieved_at": _now_iso(),
                },
            }
        ],
        "confidence": 0.85,
        "citations": [
            {
                "source_name": "yfinance",
                "url": None,
                "identifier": "AAPL",
                "snippet": None,
                "retrieved_at": _now_iso(),
            }
        ],
        "raw_data_notes": [],
        "assumptions": ["USD is the reporting currency"],
        "errors": [],
    }
    # Wrap in fences to also verify the parser's resilience.
    return "```json\n" + json.dumps(payload) + "\n```"


def _news_response() -> str:
    payload = {
        "agent_name": "news",
        "ticker": "AAPL",
        "as_of_date": _now_iso(),
        "status": "partial",
        "summary": "Mixed coverage in the past 14 days.",
        "bullet_points": ["Earnings beat reported.", "New antitrust lawsuit filed."],
        "findings": {
            "window_days": 14,
            "articles": [
                {
                    "title": "Apple beats Q1 estimates",
                    "url": "https://www.reuters.com/aapl-beat",
                    "source": "reuters.com",
                    "published_at": None,
                    "snippet": None,
                    "sentiment": "positive",
                    "sentiment_score": 0.5,
                    "relevance_score": 0.9,
                },
                {
                    "title": "Apple sued over App Store practices",
                    "url": "https://www.bloomberg.com/aapl-sued",
                    "source": "bloomberg.com",
                    "published_at": None,
                    "snippet": None,
                    "sentiment": "negative",
                    "sentiment_score": -0.5,
                    "relevance_score": 0.7,
                },
            ],
            "overall_sentiment": "neutral",
            "overall_sentiment_score": 0.125,
            "themes": ["earnings_beat", "lawsuit"],
            "citations": [],
        },
        "risks": [],
        "confidence": 0.6,
        "citations": [],
        "raw_data_notes": [],
        "assumptions": [],
        "errors": [],
    }
    return json.dumps(payload)


def _macro_response() -> str:
    indicator = _macro_indicators()[0].model_dump(mode="json")
    payload = {
        "agent_name": "macro",
        "ticker": "AAPL",
        "as_of_date": _now_iso(),
        "status": "partial",
        "summary": "Inflation still slightly above target with YoY 2.9%.",
        "bullet_points": ["CPI YoY at +2.9%."],
        "findings": {
            "indicators": [indicator],
            "regime_tags": ["inflation_in_range"],
        },
        "risks": [],
        "confidence": 0.55,
        "citations": [indicator["citation"]],
        "raw_data_notes": ["Only 1 indicator in this bundle."],
        "assumptions": [],
        "errors": [],
    }
    return json.dumps(payload)


def _filings_response() -> str:
    chunk = _retrieved_chunks()[0]
    citation = chunk.citation.model_dump(mode="json")
    payload = {
        "agent_name": "filings",
        "ticker": "AAPL",
        "as_of_date": _now_iso(),
        "status": "partial",
        "summary": "10-K flags supply chain concentration as the key structural risk.",
        "bullet_points": ["Supply chain concentrated in Asia."],
        "findings": {
            "filing_type": "10-K",
            "filing_period": None,
            "accession_number": "0000320193-24-000123",
            "filed_on": None,
            "sections": [
                {
                    "section": "risk_factors",
                    "summary": "Supply chain concentration is disclosed as a principal risk.",
                    "key_points": ["Asia supplier concentration."],
                    "citations": [citation],
                }
            ],
            "notable_risks": [
                {
                    "category": "supply_chain",
                    "title": "Asia supplier concentration",
                    "description": "Supply chain concentrated in Asia, exposing to disruptions.",
                    "severity": "high",
                    "source_section": "risk_factors",
                    "citation": citation,
                }
            ],
        },
        "risks": [
            {
                "category": "supply_chain",
                "title": "Asia supplier concentration",
                "description": "Supply chain concentrated in Asia, exposing to disruptions.",
                "severity": "high",
                "source_section": "risk_factors",
                "citation": citation,
            }
        ],
        "confidence": 0.6,
        "citations": [citation],
        "raw_data_notes": ["Only risk_factors chunks retrieved."],
        "assumptions": [],
        "errors": [],
    }
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_price_specialist_stamps_envelope():
    llm = StubLLM(_price_response())
    out = run_price_specialist("aapl", _price_metrics(), llm=llm)

    assert out.agent_name == AgentName.PRICE
    assert out.ticker == "AAPL"
    assert out.status.value == "ok"
    assert out.model_used == "stub-gemini"
    assert out.latency_ms is not None and out.latency_ms >= 0
    assert out.findings.current_price == 210.0

    # System prompt loaded from price.md and embedded
    assert "PRICE specialist" in llm.calls[0]["system"]
    # User payload must contain the tool data
    assert '"price_metrics"' in llm.calls[0]["user"]


def test_run_news_specialist_happy():
    llm = StubLLM(_news_response())
    out = run_news_specialist("AAPL", _news_items(), llm=llm)
    assert out.agent_name == AgentName.NEWS
    assert out.findings.overall_sentiment_score == pytest.approx(0.125)
    assert "earnings_beat" in out.findings.themes


def test_run_news_specialist_drops_snippets_by_default():
    """By default snippet is omitted from the LLM payload (token saver)."""
    import json as _json

    llm = StubLLM(_news_response())
    heavy_articles = [
        NewsItem(
            title="Apple beats Q1 estimates",
            url="https://www.reuters.com/aapl-beat",
            source="reuters.com",
            snippet="X" * 1200,  # deliberately huge
            sentiment=SentimentLabel.NEUTRAL,
            relevance_score=0.9,
        ),
    ]

    run_news_specialist("AAPL", heavy_articles, llm=llm)
    user_payload = llm.calls[0]["user"]
    # snippet must not be serialized into the prompt
    assert '"snippet"' not in user_payload
    assert "XXXXX" not in user_payload
    # Sanity: articles were still sent
    assert '"articles"' in user_payload
    parsed = _json.loads(user_payload.split("\n\n", 1)[1])
    assert parsed["tool_data"]["articles"][0]["title"] == "Apple beats Q1 estimates"
    assert parsed["tool_data"]["total_articles_available"] == 1


def test_run_news_specialist_trims_to_top_n_by_relevance():
    """Only the top-N articles by relevance_score reach the LLM."""
    import json as _json

    llm = StubLLM(_news_response())
    many = [
        NewsItem(
            title=f"Article {i}",
            url=f"https://example.com/a{i}",
            source="example.com",
            sentiment=SentimentLabel.NEUTRAL,
            relevance_score=float(i) / 10.0,
        )
        for i in range(10)
    ]

    run_news_specialist("AAPL", many, llm=llm, max_articles=3)
    parsed = _json.loads(llm.calls[0]["user"].split("\n\n", 1)[1])
    titles = [a["title"] for a in parsed["tool_data"]["articles"]]
    # highest-relevance first, top 3 only
    assert titles == ["Article 9", "Article 8", "Article 7"]
    assert parsed["tool_data"]["total_articles_available"] == 10


def test_run_news_specialist_include_snippet_truncates():
    """include_snippet=True truncates to snippet_chars with an ellipsis."""
    import json as _json

    llm = StubLLM(_news_response())
    articles = [
        NewsItem(
            title="Big story",
            url="https://www.reuters.com/big",
            source="reuters.com",
            snippet="A" * 500,
            sentiment=SentimentLabel.NEUTRAL,
            relevance_score=0.8,
        ),
    ]
    run_news_specialist(
        "AAPL",
        articles,
        llm=llm,
        include_snippet=True,
        snippet_chars=50,
    )
    parsed = _json.loads(llm.calls[0]["user"].split("\n\n", 1)[1])
    snippet = parsed["tool_data"]["articles"][0]["snippet"]
    assert len(snippet) == 50
    assert snippet.endswith("\u2026")


def test_run_macro_specialist_happy():
    llm = StubLLM(_macro_response())
    out = run_macro_specialist("AAPL", _macro_indicators(), llm=llm)
    assert out.agent_name == AgentName.MACRO
    assert out.findings.regime_tags == ["inflation_in_range"]


def test_run_filings_specialist_happy():
    llm = StubLLM(_filings_response())
    out = run_filings_specialist("AAPL", _retrieved_chunks(), llm=llm)
    assert out.agent_name == AgentName.FILINGS
    assert out.findings.notable_risks[0].category == "supply_chain"
    assert len(out.findings.sections) == 1


def test_self_correction_retry_on_bad_json(monkeypatch):
    """First call returns junk; second call returns valid JSON - runner recovers."""
    responses = iter(["this is not json at all", _price_response()])

    class FlipFlopLLM:
        model_name = "stub-retry"

        def generate(self, *, system, user, json_mode=True):
            return next(responses)

    out = run_price_specialist("AAPL", _price_metrics(), llm=FlipFlopLLM(), max_retries=1)
    assert out.agent_name == AgentName.PRICE


def test_exhausted_retries_raises():
    class AlwaysBadLLM:
        model_name = "stub-bad"

        def generate(self, *, system, user, json_mode=True):
            return "still not json"

    with pytest.raises(AgentOutputError):
        run_price_specialist("AAPL", _price_metrics(), llm=AlwaysBadLLM(), max_retries=1)
