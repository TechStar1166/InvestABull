"""Macroeconomic schemas consumed by the Macro specialist agent."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.common import SourceCitation, TrendDirection


class MacroIndicator(BaseModel):
    """A single FRED series observation with short-horizon context."""

    series_id: str = Field(..., description="FRED series id, e.g. 'CPIAUCSL', 'DGS10'.")
    name: str = Field(..., description="Human readable indicator name.")
    unit: str | None = Field(
        default=None, description="e.g. 'Percent', 'Index 1982-1984=100'."
    )
    frequency: str | None = Field(
        default=None, description="e.g. 'Monthly', 'Quarterly', 'Daily'."
    )

    latest_value: float
    latest_date: date

    prior_value: float | None = None
    prior_date: date | None = None

    yoy_change: float | None = Field(
        default=None,
        description="Year-over-year change as a decimal (0.032 = +3.2%).",
    )
    trend: TrendDirection = TrendDirection.FLAT

    citation: SourceCitation


class MacroDigest(BaseModel):
    """Aggregated payload emitted by the Macro agent."""

    indicators: list[MacroIndicator] = Field(default_factory=list)
    regime_tags: list[str] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "Short human tags describing the current macro regime, e.g. "
            "'disinflation', 'restrictive_policy', 'yield_curve_inverted'."
        ),
    )
