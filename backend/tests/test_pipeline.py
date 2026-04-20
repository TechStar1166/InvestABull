"""End-to-end tests for the service-layer pipeline.

Every upstream (yfinance / Tavily / FRED / SEC / ChromaDB / Gemini) is mocked
at the ``app.services.pipeline`` import boundary so these tests run offline
and in milliseconds.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.schemas.common import AgentStatus, SentimentLabel, SourceCitation, TrendDirection
from app.schemas.macro import MacroIndicator
from app.schemas.news import NewsItem
from app.schemas.price import PriceMetrics, ReturnsBundle
from app.services.pipeline import CoordinatorPayload, run_specialist_pipeline
from app.tools.base import InvalidInputError, NoDataError, UpstreamAPIError


# ---------------------------------------------------------------------------
# Shared fixtures / builders
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _metrics() -> PriceMetrics:
    return PriceMetrics(
        ticker="AAPL",
        as_of=_now(),
        current_price=210.0,
        previous_close=208.0,
        returns=ReturnsBundle(one_month=0.05, one_year=0.18),
    )


def _articles() -> list[NewsItem]:
    return [
        NewsItem(
            title="Apple beats Q1 estimates",
            url="https://www.reuters.com/aapl-beat",
            source="reuters.com",
            relevance_score=0.9,
        )
    ]


def _indicators() -> list[MacroIndicator]:
    from datetime import date

    return [
        MacroIndicator(
            series_id="CPIAUCSL",
            name="CPI",
            latest_value=312.5,
            latest_date=date(2026, 3, 1),
            yoy_change=0.029,
            trend=TrendDirection.UP,
            citation=SourceCitation(
                source_name="FRED: CPIAUCSL",
                url="https://fred.stlouisfed.org/series/CPIAUCSL",
                identifier="CPIAUCSL",
                retrieved_at=_now(),
            ),
        )
    ]


def _retrieved_chunk():
    from app.rag.retrieval import RetrievedChunk

    return RetrievedChunk(
        text="Our supply chain is concentrated in Asia.",
        score=0.91,
        chunk_id="acc:risk_factors:0",
        section="risk_factors",
        accession_number="acc",
        ticker="AAPL",
        citation=SourceCitation(
            source_name="SEC 10-K AAPL",
            url="https://www.sec.gov/demo.htm",
            identifier="acc",
            retrieved_at=_now(),
        ),
    )


# ---------------------------------------------------------------------------
# Canned LLM responses (shape matches SpecialistAgentOutput)
# ---------------------------------------------------------------------------


def _price_json() -> str:
    return json.dumps(
        {
            "agent_name": "price",
            "ticker": "AAPL",
            "as_of_date": _now_iso(),
            "status": "ok",
            "summary": "Apple trades above its 200-day MA.",
            "bullet_points": ["Up 18% YoY."],
            "findings": _metrics().model_dump(mode="json"),
            "risks": [],
            "confidence": 0.85,
            "citations": [],
            "raw_data_notes": [],
            "assumptions": [],
            "errors": [],
        }
    )


def _news_json() -> str:
    return json.dumps(
        {
            "agent_name": "news",
            "ticker": "AAPL",
            "as_of_date": _now_iso(),
            "status": "ok",
            "summary": "Mostly positive coverage.",
            "bullet_points": ["Earnings beat."],
            "findings": {
                "window_days": 14,
                "articles": [
                    {
                        "title": "Apple beats Q1 estimates",
                        "url": "https://www.reuters.com/aapl-beat",
                        "source": "reuters.com",
                        "sentiment": "positive",
                        "sentiment_score": 0.6,
                        "relevance_score": 0.9,
                    }
                ],
                "overall_sentiment": "positive",
                "overall_sentiment_score": 0.6,
                "themes": ["earnings_beat"],
                "citations": [],
            },
            "risks": [],
            "confidence": 0.7,
            "citations": [],
            "raw_data_notes": [],
            "assumptions": [],
            "errors": [],
        }
    )


def _macro_json() -> str:
    ind = _indicators()[0].model_dump(mode="json")
    return json.dumps(
        {
            "agent_name": "macro",
            "ticker": "AAPL",
            "as_of_date": _now_iso(),
            "status": "ok",
            "summary": "Inflation near target.",
            "bullet_points": ["CPI +2.9% YoY."],
            "findings": {"indicators": [ind], "regime_tags": ["inflation_in_range"]},
            "risks": [],
            "confidence": 0.6,
            "citations": [ind["citation"]],
            "raw_data_notes": [],
            "assumptions": [],
            "errors": [],
        }
    )


def _filings_json() -> str:
    citation = _retrieved_chunk().citation.model_dump(mode="json")
    return json.dumps(
        {
            "agent_name": "filings",
            "ticker": "AAPL",
            "as_of_date": _now_iso(),
            "status": "ok",
            "summary": "Supply chain concentration is a key risk.",
            "bullet_points": ["Asia supplier concentration."],
            "findings": {
                "filing_type": "10-K",
                "filing_period": None,
                "accession_number": "acc",
                "filed_on": None,
                "sections": [
                    {
                        "section": "risk_factors",
                        "summary": "Supply chain concentration disclosed.",
                        "key_points": ["Asia concentration."],
                        "citations": [citation],
                    }
                ],
                "notable_risks": [
                    {
                        "category": "supply_chain",
                        "title": "Asia concentration",
                        "description": "Supply chain concentrated in Asia.",
                        "severity": "high",
                        "source_section": "risk_factors",
                        "citation": citation,
                    }
                ],
            },
            "risks": [],
            "confidence": 0.65,
            "citations": [citation],
            "raw_data_notes": [],
            "assumptions": [],
            "errors": [],
        }
    )


# ---------------------------------------------------------------------------
# Routing stub LLM
# ---------------------------------------------------------------------------


class RoutingStubLLM:
    """Dispatch canned responses based on which specialist system prompt we saw."""

    model_name = "stub-gemini"

    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping
        self.calls: list[str] = []

    def generate(self, *, system: str, user: str, json_mode: bool = True) -> str:
        for keyword, response in self._mapping.items():
            if keyword in system:
                self.calls.append(keyword)
                return response
        raise AssertionError(f"Unexpected system prompt: {system[:120]!r}")


def _default_router() -> RoutingStubLLM:
    return RoutingStubLLM(
        {
            "PRICE specialist": _price_json(),
            "NEWS specialist": _news_json(),
            "MACRO specialist": _macro_json(),
            "FILINGS specialist": _filings_json(),
        }
    )


# ---------------------------------------------------------------------------
# Upstream monkeypatches
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal ``ChromaStore``-shaped stub used by the pipeline tests.

    Only ``has_ticker`` is touched by the pipeline; retrieval and ingestion
    are patched at the module boundary below.
    """

    def __init__(self, *, has_ticker: bool = False) -> None:
        self._has_ticker = has_ticker
        self.has_ticker_calls: list[str] = []

    def has_ticker(self, ticker: str) -> bool:
        self.has_ticker_calls.append(ticker)
        return self._has_ticker


@pytest.fixture
def mock_store():
    """Fake store that reports "nothing ingested yet" by default."""
    return _FakeStore(has_ticker=False)


@pytest.fixture
def happy_path(monkeypatch, mock_store):
    """Patch every upstream at the pipeline import boundary with happy-path values."""
    import app.services.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "fetch_price_metrics", lambda t: _metrics())
    monkeypatch.setattr(pipeline_mod, "search_ticker_news", lambda t: _articles())
    monkeypatch.setattr(pipeline_mod, "fetch_macro_bundle", lambda: _indicators())
    monkeypatch.setattr(
        pipeline_mod,
        "ingest_latest_10k_if_missing",
        lambda ticker, store: None,
    )
    monkeypatch.setattr(
        pipeline_mod,
        "retrieve_filing_context",
        lambda store, ticker: [_retrieved_chunk()],
    )
    return mock_store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pipeline_happy_path_returns_four_envelopes(happy_path):
    payload = run_specialist_pipeline(
        "aapl", llm=_default_router(), store=happy_path
    )

    assert isinstance(payload, CoordinatorPayload)
    assert payload.ticker == "AAPL"  # normalized
    assert payload.correlation_id
    assert payload.latency_ms >= 0
    assert payload.finished_at >= payload.started_at

    assert payload.price.status is AgentStatus.OK
    assert payload.news.status is AgentStatus.OK
    assert payload.macro.status is AgentStatus.OK
    assert payload.filings.status is AgentStatus.OK

    assert payload.price.findings.current_price == 210.0
    assert payload.filings.findings.notable_risks[0].category == "supply_chain"
    assert payload.news.findings.overall_sentiment is SentimentLabel.POSITIVE
    assert payload.macro.findings.regime_tags == ["inflation_in_range"]


def test_pipeline_invalid_ticker_raises_before_fanout():
    with pytest.raises(InvalidInputError):
        run_specialist_pipeline("not a ticker", llm=_default_router(), store=object())


def test_pipeline_price_tool_failure_produces_failed_envelope(
    monkeypatch, mock_store
):
    import app.services.pipeline as pipeline_mod

    def _boom(_t):
        raise UpstreamAPIError("yfinance 502")

    monkeypatch.setattr(pipeline_mod, "fetch_price_metrics", _boom)
    monkeypatch.setattr(pipeline_mod, "search_ticker_news", lambda t: _articles())
    monkeypatch.setattr(pipeline_mod, "fetch_macro_bundle", lambda: _indicators())
    monkeypatch.setattr(pipeline_mod, "ingest_latest_10k_if_missing", lambda t, s: None)
    monkeypatch.setattr(
        pipeline_mod, "retrieve_filing_context", lambda s, t: [_retrieved_chunk()]
    )

    payload = run_specialist_pipeline("AAPL", llm=_default_router(), store=mock_store)

    assert payload.price.status is AgentStatus.FAILED
    assert payload.price.errors and "yfinance 502" in payload.price.errors[0]
    assert payload.price.confidence == 0.0
    # Other three specialists still succeed - one bad upstream is isolated.
    assert payload.news.status is AgentStatus.OK
    assert payload.filings.status is AgentStatus.OK
    assert payload.macro.status is AgentStatus.OK


def test_pipeline_news_no_data_still_runs_specialist(monkeypatch, mock_store):
    """NoDataError from Tavily should become an empty-article specialist run, not a failure."""
    import app.services.pipeline as pipeline_mod

    def _no_data(_t):
        raise NoDataError("no articles")

    monkeypatch.setattr(pipeline_mod, "fetch_price_metrics", lambda t: _metrics())
    monkeypatch.setattr(pipeline_mod, "search_ticker_news", _no_data)
    monkeypatch.setattr(pipeline_mod, "fetch_macro_bundle", lambda: _indicators())
    monkeypatch.setattr(pipeline_mod, "ingest_latest_10k_if_missing", lambda t, s: None)
    monkeypatch.setattr(
        pipeline_mod, "retrieve_filing_context", lambda s, t: [_retrieved_chunk()]
    )

    # Emit a valid empty-articles news response.
    empty_news = json.dumps(
        {
            "agent_name": "news",
            "ticker": "AAPL",
            "as_of_date": _now_iso(),
            "status": "no_data",
            "summary": "No material articles in the last 14 days.",
            "bullet_points": [],
            "findings": {
                "window_days": 14,
                "articles": [],
                "overall_sentiment": "neutral",
                "overall_sentiment_score": None,
                "themes": [],
                "citations": [],
            },
            "risks": [],
            "confidence": 0.3,
            "citations": [],
            "raw_data_notes": ["Tavily returned zero results."],
            "assumptions": [],
            "errors": [],
        }
    )
    llm = RoutingStubLLM(
        {
            "PRICE specialist": _price_json(),
            "NEWS specialist": empty_news,
            "MACRO specialist": _macro_json(),
            "FILINGS specialist": _filings_json(),
        }
    )

    payload = run_specialist_pipeline("AAPL", llm=llm, store=mock_store)

    assert payload.news.status is AgentStatus.NO_DATA
    assert payload.news.findings.articles == []
    assert payload.news.errors == []
    # The other three are unaffected.
    assert payload.price.status is AgentStatus.OK


def test_pipeline_filings_no_chunks_yields_no_data_envelope(
    monkeypatch, mock_store
):
    import app.services.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "fetch_price_metrics", lambda t: _metrics())
    monkeypatch.setattr(pipeline_mod, "search_ticker_news", lambda t: _articles())
    monkeypatch.setattr(pipeline_mod, "fetch_macro_bundle", lambda: _indicators())
    monkeypatch.setattr(pipeline_mod, "ingest_latest_10k_if_missing", lambda t, s: None)
    monkeypatch.setattr(pipeline_mod, "retrieve_filing_context", lambda s, t: [])

    payload = run_specialist_pipeline(
        "AAPL", llm=_default_router(), store=mock_store
    )

    assert payload.filings.status is AgentStatus.NO_DATA
    assert "no relevant chunks" in payload.filings.errors[0]


def test_coordinator_bridge_prompt_contains_all_four_envelopes(happy_path):
    from app.services.coordinator_bridge import build_coordinator_prompt

    payload = run_specialist_pipeline(
        "AAPL", llm=_default_router(), store=happy_path
    )
    system, user = build_coordinator_prompt(payload)

    assert "Coordinator Agent" in system
    for label in ("### PRICE", "### FILINGS", "### NEWS", "### MACRO"):
        assert label in user
    assert payload.correlation_id in user


# ---------------------------------------------------------------------------
# Ingestion-skipping behaviour (speed optimization)
# ---------------------------------------------------------------------------


def test_pipeline_skips_10k_ingest_when_ticker_already_in_store(monkeypatch):
    """Hot path: when store.has_ticker is True, we must NOT hit SEC EDGAR."""
    import app.services.pipeline as pipeline_mod

    ingest_calls: list[str] = []

    def _spy_ingest(ticker, store):
        ingest_calls.append(ticker)

    monkeypatch.setattr(pipeline_mod, "fetch_price_metrics", lambda t: _metrics())
    monkeypatch.setattr(pipeline_mod, "search_ticker_news", lambda t: _articles())
    monkeypatch.setattr(pipeline_mod, "fetch_macro_bundle", lambda: _indicators())
    monkeypatch.setattr(pipeline_mod, "ingest_latest_10k_if_missing", _spy_ingest)
    monkeypatch.setattr(
        pipeline_mod, "retrieve_filing_context", lambda s, t: [_retrieved_chunk()]
    )

    cached_store = _FakeStore(has_ticker=True)
    payload = run_specialist_pipeline(
        "AAPL", llm=_default_router(), store=cached_store
    )

    assert ingest_calls == [], "must not attempt ingestion when cached"
    assert cached_store.has_ticker_calls == ["AAPL"]
    assert payload.filings.status is AgentStatus.OK


def test_pipeline_ingests_when_ticker_missing_from_store(monkeypatch):
    """Cold path: when the ticker is unknown, we DO call the ingester."""
    import app.services.pipeline as pipeline_mod

    ingest_calls: list[str] = []

    def _spy_ingest(ticker, store):
        ingest_calls.append(ticker)

    monkeypatch.setattr(pipeline_mod, "fetch_price_metrics", lambda t: _metrics())
    monkeypatch.setattr(pipeline_mod, "search_ticker_news", lambda t: _articles())
    monkeypatch.setattr(pipeline_mod, "fetch_macro_bundle", lambda: _indicators())
    monkeypatch.setattr(pipeline_mod, "ingest_latest_10k_if_missing", _spy_ingest)
    monkeypatch.setattr(
        pipeline_mod, "retrieve_filing_context", lambda s, t: [_retrieved_chunk()]
    )

    cold_store = _FakeStore(has_ticker=False)
    run_specialist_pipeline("AAPL", llm=_default_router(), store=cold_store)

    assert ingest_calls == ["AAPL"]


def test_pipeline_read_only_mode_returns_no_data_without_ingesting(monkeypatch):
    """FILINGS_READ_ONLY=true: missing ticker -> NO_DATA envelope, no EDGAR hit."""
    import app.services.pipeline as pipeline_mod
    from app.config import get_settings

    # Flip the setting for this test; restore afterwards.
    settings = get_settings()
    monkeypatch.setattr(settings, "filings_read_only", True)

    ingest_calls: list[str] = []

    def _spy_ingest(ticker, store):
        ingest_calls.append(ticker)

    monkeypatch.setattr(pipeline_mod, "fetch_price_metrics", lambda t: _metrics())
    monkeypatch.setattr(pipeline_mod, "search_ticker_news", lambda t: _articles())
    monkeypatch.setattr(pipeline_mod, "fetch_macro_bundle", lambda: _indicators())
    monkeypatch.setattr(pipeline_mod, "ingest_latest_10k_if_missing", _spy_ingest)
    monkeypatch.setattr(
        pipeline_mod, "retrieve_filing_context", lambda s, t: [_retrieved_chunk()]
    )

    cold_store = _FakeStore(has_ticker=False)
    payload = run_specialist_pipeline(
        "AAPL", llm=_default_router(), store=cold_store
    )

    assert ingest_calls == []
    assert payload.filings.status is AgentStatus.NO_DATA
    assert "read-only" in payload.filings.errors[0]
    # Other specialists are unaffected by filings read-only mode.
    assert payload.price.status is AgentStatus.OK
    assert payload.news.status is AgentStatus.OK
    assert payload.macro.status is AgentStatus.OK
