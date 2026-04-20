"""Primitive types and enums reused across every agent schema.

Design notes
------------
* Enums are ``str``-valued so they serialize cleanly to JSON and are readable
  by the coordinator LLM without extra casting.
* ``SourceCitation`` is the single citation shape produced by every tool.
  Every factual claim a specialist agent makes must map back to at least one
  ``SourceCitation`` so the final memo is fully auditable.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, field_validator


class AgentName(str, Enum):
    """Canonical names of the four specialist agents."""

    PRICE = "price"
    FILINGS = "filings"
    NEWS = "news"
    MACRO = "macro"


class AgentStatus(str, Enum):
    """Lifecycle status reported by a specialist agent.

    OK       - All required tool calls succeeded and output is trustworthy.
    PARTIAL  - Some data is missing; findings are usable but incomplete.
    NO_DATA  - No usable data was returned (e.g. unknown ticker).
    FAILED   - An unrecoverable error occurred; see ``errors`` field.
    """

    OK = "ok"
    PARTIAL = "partial"
    NO_DATA = "no_data"
    FAILED = "failed"


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TrendDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class SourceCitation(BaseModel):
    """A single auditable reference backing a fact emitted by an agent."""

    source_name: str = Field(
        ...,
        description="Human readable source name, e.g. 'SEC 10-K AAPL 2024', "
        "'Tavily: reuters.com', 'FRED: CPIAUCSL', 'yfinance'.",
    )
    url: HttpUrl | None = Field(
        default=None, description="Canonical URL when one exists."
    )
    identifier: str | None = Field(
        default=None,
        description=(
            "Provider-native identifier (CIK/accession number, FRED series id, "
            "Tavily result id, etc.) for programmatic re-retrieval."
        ),
    )
    snippet: str | None = Field(
        default=None,
        max_length=8_000,
        description="Excerpt supporting the citation (SEC/RAG snippets can be long).",
    )
    retrieved_at: datetime = Field(
        ..., description="UTC timestamp when the source was fetched."
    )

    @field_validator("source_name")
    @classmethod
    def _strip_source_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("source_name must be non-empty")
        return v
