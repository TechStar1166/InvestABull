"""Generic envelope emitted by every specialist agent.

The coordinator (Claude 3.5 Sonnet) always sees this exact shape; only the
``findings`` payload varies by agent. Keeping the envelope identical makes it
trivial to cross-compare agents (status, confidence, risks, citations) when
synthesizing the investment memo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import AgentName, AgentStatus, SourceCitation
from app.schemas.filings import FilingsFindings, RiskItem
from app.schemas.macro import MacroDigest
from app.schemas.news import NewsDigest
from app.schemas.price import PriceMetrics

T = TypeVar("T", bound=BaseModel)


class SpecialistAgentOutput(BaseModel, Generic[T]):
    """Uniform container every specialist agent returns.

    Parameters
    ----------
    T
        The agent-specific payload type (e.g. ``PriceMetrics``,
        ``FilingsFindings``). This keeps each agent's domain data strongly
        typed while preserving a shared envelope.
    """

    agent_name: AgentName
    ticker: str
    as_of_date: datetime = Field(
        ..., description="UTC timestamp the agent completed its run."
    )
    status: AgentStatus = AgentStatus.OK

    summary: str = Field(
        ...,
        max_length=2_000,
        description=(
            "2-4 sentence executive summary. The ONLY field allowed to contain "
            "free-form prose; everything else must be structured."
        ),
    )
    bullet_points: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Up to 10 short, self-contained takeaways.",
    )

    findings: T = Field(..., description="Strongly-typed agent-specific payload.")
    risks: list[RiskItem] = Field(default_factory=list)

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Self-reported confidence in [0, 1].",
    )
    citations: list[SourceCitation] = Field(default_factory=list)
    raw_data_notes: list[str] = Field(
        default_factory=list,
        description=(
            "Terse notes about provenance / caveats of the raw data "
            "(e.g. 'pe_ttm missing from yfinance', 'FRED value revised')."
        ),
    )

    assumptions: list[str] = Field(
        default_factory=list,
        description="Explicit assumptions the agent made when interpreting data.",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Non-fatal errors encountered during the run.",
    )

    model_used: str | None = Field(
        default=None, description="LLM model id, e.g. 'gemini-2.5-flash'."
    )
    latency_ms: int | None = Field(
        default=None, ge=0, description="End-to-end wall-clock latency."
    )

    @field_validator("ticker")
    @classmethod
    def _upper_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("ticker must be non-empty")
        return v


# ----- Concrete per-agent aliases -------------------------------------------------

PriceAgentOutput = SpecialistAgentOutput[PriceMetrics]
FilingsAgentOutput = SpecialistAgentOutput[FilingsFindings]
NewsAgentOutput = SpecialistAgentOutput[NewsDigest]
MacroAgentOutput = SpecialistAgentOutput[MacroDigest]
