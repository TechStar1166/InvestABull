"""News / sentiment schemas consumed by the News specialist agent."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.schemas.common import SentimentLabel, SourceCitation


class NewsItem(BaseModel):
    """A single normalized news article relevant to a ticker."""

    title: str = Field(..., max_length=300)
    url: HttpUrl
    source: str = Field(..., description="Publisher domain or name, e.g. 'reuters.com'.")
    published_at: datetime | None = None
    snippet: str | None = Field(default=None, max_length=1_500)

    sentiment: SentimentLabel = SentimentLabel.NEUTRAL
    sentiment_score: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="Numeric sentiment in [-1, 1]; negative is bearish.",
    )
    relevance_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Provider-supplied relevance score for the query, if available.",
    )


class NewsDigest(BaseModel):
    """Aggregated payload emitted by the News agent."""

    window_days: int = Field(
        default=14,
        ge=1,
        le=90,
        description="Trailing window used when pulling articles.",
    )
    articles: list[NewsItem] = Field(default_factory=list)

    overall_sentiment: SentimentLabel = SentimentLabel.NEUTRAL
    overall_sentiment_score: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="Mean of per-article sentiment_score, weighted by relevance.",
    )
    themes: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Short tags for the dominant narratives, e.g. 'AI capex', "
        "'FDA approval', 'guidance cut'.",
    )
    citations: list[SourceCitation] = Field(default_factory=list)
