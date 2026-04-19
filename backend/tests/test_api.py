"""Integration tests for the FastAPI ``/research`` endpoint.

We patch ``main.run_specialist_pipeline`` so we never hit yfinance / Tavily /
FRED / SEC / Gemini; the test exercises the HTTP layer only (serialization,
error mapping, CORS, request-id middleware).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.schemas.common import (
    AgentName,
    AgentStatus,
    SentimentLabel,
    SourceCitation,
    TrendDirection,
)
from app.schemas.filings import FilingsFindings
from app.schemas.macro import MacroDigest, MacroIndicator
from app.schemas.news import NewsDigest, NewsItem
from app.schemas.price import PriceMetrics, ReturnsBundle
from app.schemas.specialist import (
    FilingsAgentOutput,
    MacroAgentOutput,
    NewsAgentOutput,
    PriceAgentOutput,
)
from app.services.pipeline import CoordinatorPayload
from app.tools.base import InvalidInputError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ok_payload(ticker: str = "AAPL") -> CoordinatorPayload:
    now = _now()
    from datetime import date

    macro_citation = SourceCitation(
        source_name="FRED: CPIAUCSL",
        url="https://fred.stlouisfed.org/series/CPIAUCSL",
        identifier="CPIAUCSL",
        retrieved_at=now,
    )

    price = PriceAgentOutput(
        agent_name=AgentName.PRICE,
        ticker=ticker,
        as_of_date=now,
        status=AgentStatus.OK,
        summary="Price looks healthy.",
        findings=PriceMetrics(
            ticker=ticker,
            as_of=now,
            current_price=210.0,
            returns=ReturnsBundle(one_year=0.18),
        ),
        confidence=0.85,
    )
    news = NewsAgentOutput(
        agent_name=AgentName.NEWS,
        ticker=ticker,
        as_of_date=now,
        status=AgentStatus.OK,
        summary="Mixed but leaning positive.",
        findings=NewsDigest(
            window_days=14,
            articles=[
                NewsItem(
                    title="Beat",
                    url="https://www.reuters.com/aapl",
                    source="reuters.com",
                    sentiment=SentimentLabel.POSITIVE,
                )
            ],
            overall_sentiment=SentimentLabel.POSITIVE,
        ),
        confidence=0.7,
    )
    macro = MacroAgentOutput(
        agent_name=AgentName.MACRO,
        ticker=ticker,
        as_of_date=now,
        status=AgentStatus.OK,
        summary="Disinflation trend intact.",
        findings=MacroDigest(
            indicators=[
                MacroIndicator(
                    series_id="CPIAUCSL",
                    name="CPI",
                    latest_value=312.5,
                    latest_date=date(2026, 3, 1),
                    yoy_change=0.029,
                    trend=TrendDirection.UP,
                    citation=macro_citation,
                )
            ],
            regime_tags=["inflation_in_range"],
        ),
        confidence=0.6,
    )
    filings = FilingsAgentOutput(
        agent_name=AgentName.FILINGS,
        ticker=ticker,
        as_of_date=now,
        status=AgentStatus.OK,
        summary="Supply chain concentration.",
        findings=FilingsFindings(filing_type="10-K"),
        confidence=0.6,
    )
    return CoordinatorPayload(
        correlation_id="test-corr-id",
        ticker=ticker,
        started_at=now,
        finished_at=now,
        latency_ms=42,
        price=price,
        filings=filings,
        news=news,
        macro=macro,
    )


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient with the pipeline function stubbed."""
    import main as main_mod

    def _fake_pipeline(ticker: str):
        # Mimic the real runner's input validation error mapping.
        if ticker.lower().startswith("bad"):
            raise InvalidInputError(f"ticker {ticker!r} is not a valid symbol")
        if ticker.lower() == "explode":
            raise RuntimeError("upstream meltdown")
        return _ok_payload(ticker.upper())

    monkeypatch.setattr(main_mod, "run_specialist_pipeline", _fake_pipeline)
    return TestClient(main_mod.app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "investabull-backend"


def test_research_happy_path_shape(client):
    r = client.post("/research", json={"ticker": "aapl"})
    assert r.status_code == 200

    body = r.json()
    assert body["ticker"] == "AAPL"
    assert body["correlation_id"] == "test-corr-id"
    for key in ("price", "filings", "news", "macro"):
        env = body[key]
        assert env["ticker"] == "AAPL"
        assert env["status"] == "ok"
        assert "findings" in env
        assert "confidence" in env

    # Request-id middleware echoes the header.
    assert "x-request-id" in {h.lower() for h in r.headers.keys()}


def test_research_preserves_client_request_id(client):
    r = client.post(
        "/research",
        json={"ticker": "AAPL"},
        headers={"X-Request-ID": "client-supplied-id"},
    )
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == "client-supplied-id"


def test_research_invalid_ticker_returns_400(client):
    r = client.post("/research", json={"ticker": "bad!!"})
    assert r.status_code == 400
    assert "not a valid symbol" in r.json()["detail"]


def test_research_unexpected_error_returns_500(client):
    r = client.post("/research", json={"ticker": "explode"})
    assert r.status_code == 500
    assert "upstream meltdown" in r.json()["detail"]


def test_research_request_schema_validation(client):
    r = client.post("/research", json={})
    assert r.status_code == 422  # FastAPI body validation


def test_openapi_schema_advertises_endpoint(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert "/research" in spec["paths"]
    assert "/health" in spec["paths"]
