"""Pydantic schemas shared across tools, agents, and the API layer.

Everything a specialist agent emits flows through these types so the
coordinator (Claude 3.5 Sonnet) always receives a predictable shape.
"""

from app.schemas.common import (
    AgentName,
    AgentStatus,
    RiskSeverity,
    SentimentLabel,
    SourceCitation,
    TrendDirection,
)
from app.schemas.filings import FilingsFindings, FilingSectionSummary, RiskItem
from app.schemas.macro import MacroDigest, MacroIndicator
from app.schemas.news import NewsDigest, NewsItem
from app.schemas.price import PriceMetrics, ReturnsBundle
from app.schemas.specialist import (
    FilingsAgentOutput,
    MacroAgentOutput,
    NewsAgentOutput,
    PriceAgentOutput,
    SpecialistAgentOutput,
)

__all__ = [
    "AgentName",
    "AgentStatus",
    "FilingSectionSummary",
    "FilingsAgentOutput",
    "FilingsFindings",
    "MacroAgentOutput",
    "MacroDigest",
    "MacroIndicator",
    "NewsAgentOutput",
    "NewsDigest",
    "NewsItem",
    "PriceAgentOutput",
    "PriceMetrics",
    "ReturnsBundle",
    "RiskItem",
    "RiskSeverity",
    "SentimentLabel",
    "SourceCitation",
    "SpecialistAgentOutput",
    "TrendDirection",
]
