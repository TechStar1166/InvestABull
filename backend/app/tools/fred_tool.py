"""FRED (Federal Reserve Economic Data) tool implementation.

Returns strictly-typed :class:`~app.schemas.macro.MacroIndicator` objects.
Sentiment / regime inference is an agent concern; at the tool layer we only
emit raw observations plus a conservative ``trend`` tag and a YoY pct change.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from fredapi import Fred

from app.config import get_settings
from app.schemas.common import SourceCitation, TrendDirection
from app.schemas.macro import MacroIndicator
from app.tools.base import (
    InvalidInputError,
    NoDataError,
    UpstreamAPIError,
    with_retries,
)

logger = logging.getLogger(__name__)

DEFAULT_MACRO_SERIES: tuple[str, ...] = (
    "CPIAUCSL",   # CPI, All Urban Consumers
    "FEDFUNDS",   # Federal Funds Effective Rate
    "DGS10",      # 10Y Treasury Constant Maturity
    "DGS2",       # 2Y Treasury Constant Maturity
    "UNRATE",     # Unemployment Rate
    "GDPC1",      # Real GDP
    "UMCSENT",    # U. Michigan Consumer Sentiment
)


def _fred_client() -> Fred:
    settings = get_settings()
    if not settings.fred_api_key:
        raise UpstreamAPIError("FRED_API_KEY is not configured")
    return Fred(api_key=settings.fred_api_key)


def _trend(series: pd.Series, lookback: int = 3, tol: float = 0.01) -> TrendDirection:
    """Compare latest to value ``lookback`` observations ago.

    Changes within +/-``tol`` (default 1%) are treated as flat so we don't
    over-interpret noisy high-frequency series.
    """
    if series is None or len(series) < lookback + 1:
        return TrendDirection.FLAT
    latest = float(series.iloc[-1])
    prior = float(series.iloc[-1 - lookback])
    if prior == 0:
        return TrendDirection.FLAT
    change = (latest - prior) / abs(prior)
    if change > tol:
        return TrendDirection.UP
    if change < -tol:
        return TrendDirection.DOWN
    return TrendDirection.FLAT


def _yoy(series: pd.Series) -> float | None:
    """Year-over-year pct change using the nearest prior obs to ``t - 365d``."""
    if series is None or series.empty:
        return None
    latest_date = series.index[-1]
    target = latest_date - pd.Timedelta(days=365)
    window = series.loc[series.index <= target]
    if window.empty:
        return None
    prior = float(window.iloc[-1])
    latest = float(series.iloc[-1])
    if prior == 0:
        return None
    return latest / prior - 1.0


def _info_field(info: Any, key: str) -> str | None:
    """Safely pull a field from ``fredapi``'s Series-shaped info object."""
    if info is None:
        return None
    try:
        value = info[key]
    except (KeyError, IndexError, AttributeError):
        return None
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


@with_retries
def fetch_indicator(series_id: str) -> MacroIndicator:
    """Return the latest observation + context for a FRED series.

    Raises
    ------
    InvalidInputError
        If ``series_id`` is empty or non-string.
    NoDataError
        If FRED reports no observations for the series.
    UpstreamAPIError
        For other API errors.
    """
    if not isinstance(series_id, str) or not series_id.strip():
        raise InvalidInputError("series_id must be a non-empty string")
    sid = series_id.strip().upper()

    fred = _fred_client()
    try:
        raw_series = fred.get_series(sid)
        info = fred.get_series_info(sid)
    except ValueError as e:
        # fredapi surfaces HTTP 400 (unknown series) as ValueError
        raise NoDataError(f"FRED series {sid!r} not found: {e}") from e
    except Exception as e:
        raise UpstreamAPIError(f"FRED fetch failed for {sid}: {e}") from e

    series = raw_series.dropna() if raw_series is not None else pd.Series(dtype=float)
    if series.empty:
        raise NoDataError(f"FRED returned no observations for {sid}")

    latest_date = pd.Timestamp(series.index[-1]).date()
    latest_value = float(series.iloc[-1])
    prior_value: float | None = None
    prior_date = None
    if len(series) >= 2:
        prior_value = float(series.iloc[-2])
        prior_date = pd.Timestamp(series.index[-2]).date()

    name = _info_field(info, "title") or sid
    unit = _info_field(info, "units")
    freq = _info_field(info, "frequency")

    citation = SourceCitation(
        source_name=f"FRED: {sid}",
        url=f"https://fred.stlouisfed.org/series/{sid}",
        identifier=sid,
        snippet=name,
        retrieved_at=datetime.now(timezone.utc),
    )

    return MacroIndicator(
        series_id=sid,
        name=name,
        unit=unit,
        frequency=freq,
        latest_value=latest_value,
        latest_date=latest_date,
        prior_value=prior_value,
        prior_date=prior_date,
        yoy_change=_yoy(series),
        trend=_trend(series),
        citation=citation,
    )


def fetch_macro_bundle(
    series_ids: tuple[str, ...] | list[str] = DEFAULT_MACRO_SERIES,
) -> list[MacroIndicator]:
    """Fetch several FRED indicators in sequence.

    Per-series failures are logged and the series is skipped; callers should
    detect missing ids via ``len(result) < len(series_ids)`` and surface them
    on the agent envelope as ``raw_data_notes``.
    """
    results: list[MacroIndicator] = []
    for sid in series_ids:
        try:
            results.append(fetch_indicator(sid))
        except (NoDataError, UpstreamAPIError, InvalidInputError) as e:
            logger.warning("FRED series %s skipped: %s", sid, e)
            continue
    return results
