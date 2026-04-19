"""Price / quantitative schemas consumed by the Price specialist agent."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class ReturnsBundle(BaseModel):
    """Total returns over common trailing windows, expressed as decimals.

    A value of ``0.1234`` means +12.34%.
    """

    one_month: float | None = None
    three_month: float | None = None
    six_month: float | None = None
    ytd: float | None = None
    one_year: float | None = None


class PriceMetrics(BaseModel):
    """Normalized quantitative snapshot for a single ticker."""

    ticker: str
    as_of: datetime = Field(
        ..., description="UTC timestamp the snapshot is valid for."
    )
    currency: str = Field(default="USD", description="ISO-4217 currency code.")

    # Spot pricing
    current_price: float | None = None
    previous_close: float | None = None
    day_change_pct: float | None = Field(
        default=None, description="Intraday change as a decimal (0.01 = 1%)."
    )

    # Range / valuation
    week_52_high: float | None = None
    week_52_low: float | None = None
    market_cap: float | None = Field(default=None, description="In reporting currency.")
    pe_ttm: float | None = None
    pe_forward: float | None = None
    eps_ttm: float | None = None
    dividend_yield: float | None = Field(
        default=None, description="Trailing yield as a decimal (0.015 = 1.5%)."
    )
    beta: float | None = None

    # Liquidity & volatility
    avg_volume_30d: float | None = None
    volatility_30d: float | None = Field(
        default=None,
        description="Annualized std-dev of daily log returns over ~30 trading days.",
    )

    # Technicals
    moving_avg_50d: float | None = None
    moving_avg_200d: float | None = None

    # Returns
    returns: ReturnsBundle = Field(default_factory=ReturnsBundle)

    # Corporate calendar (optional but handy for the agent)
    next_earnings_date: date | None = None

    @field_validator("ticker")
    @classmethod
    def _upper_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("ticker must be non-empty")
        return v
