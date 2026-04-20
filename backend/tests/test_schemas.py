"""Sanity tests for the shared Pydantic schemas."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import (
    AgentName,
    AgentStatus,
    FilingsAgentOutput,
    FilingsFindings,
    MacroAgentOutput,
    MacroDigest,
    NewsAgentOutput,
    NewsDigest,
    PriceAgentOutput,
    PriceMetrics,
    ReturnsBundle,
)


def test_price_agent_output_roundtrip():
    now = datetime.now(timezone.utc)
    out = PriceAgentOutput(
        agent_name=AgentName.PRICE,
        ticker="aapl",
        as_of_date=now,
        status=AgentStatus.OK,
        summary="demo",
        findings=PriceMetrics(
            ticker="AAPL", as_of=now, current_price=210.0,
            returns=ReturnsBundle(one_month=0.03),
        ),
        confidence=0.8,
    )
    assert out.ticker == "AAPL"
    rt = PriceAgentOutput.model_validate_json(out.model_dump_json())
    assert rt.findings.current_price == 210.0


def test_confidence_bounds():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        NewsAgentOutput(
            agent_name=AgentName.NEWS, ticker="AAPL", as_of_date=now,
            status=AgentStatus.OK, summary="x", findings=NewsDigest(),
            confidence=1.5,
        )


def test_filings_and_macro_construct():
    now = datetime.now(timezone.utc)
    FilingsAgentOutput(
        agent_name=AgentName.FILINGS, ticker="AAPL", as_of_date=now,
        status=AgentStatus.OK, summary="x", findings=FilingsFindings(),
        confidence=0.5,
    )
    MacroAgentOutput(
        agent_name=AgentName.MACRO, ticker="AAPL", as_of_date=now,
        status=AgentStatus.OK, summary="x", findings=MacroDigest(),
        confidence=0.5,
    )
