"""yfinance tool implementation.

Returns a strictly-typed :class:`~app.schemas.price.PriceMetrics` snapshot plus
a raw OHLCV helper used by the Price specialist agent for ad-hoc calculations.

Normalization rules enforced here:

* Tickers: upper-cased, regex-validated before any network call.
* Percentages: always expressed as decimals (``0.0325`` == +3.25%).
* Volatility: annualized standard deviation of daily simple returns over the
  last 30 trading days (``std * sqrt(252)``).
* NaNs and infinities are coerced to ``None`` so downstream Pydantic
  validation never fails on malformed provider data.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from app.schemas.price import PriceMetrics, ReturnsBundle
from app.tools.base import (
    NoDataError,
    UpstreamAPIError,
    validate_ticker,
    with_retries,
)

logger = logging.getLogger(__name__)


def _f(v: Any) -> float | None:
    """Coerce ``v`` to ``float``; return ``None`` for NaN/inf/missing values."""
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(fv) or math.isinf(fv):
        return None
    return fv


def _year_start(end_ts: pd.Timestamp) -> pd.Timestamp:
    tz = getattr(end_ts, "tz", None) or getattr(end_ts, "tzinfo", None)
    return pd.Timestamp(end_ts.year, 1, 1, tz=tz) if tz else pd.Timestamp(end_ts.year, 1, 1)


def _pct_return(series: pd.Series, days: int) -> float | None:
    """Total return over roughly ``days`` calendar days."""
    if series is None or series.empty or days <= 0:
        return None
    end_ts = series.index[-1]
    target_ts = end_ts - pd.Timedelta(days=days)
    window = series.loc[series.index <= target_ts]
    if window.empty:
        return None
    start_px = float(window.iloc[-1])
    end_px = float(series.iloc[-1])
    if start_px <= 0:
        return None
    return end_px / start_px - 1.0


def _ytd_return(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    end_ts = series.index[-1]
    window = series.loc[series.index >= _year_start(end_ts)]
    if window.empty:
        return None
    start_px = float(window.iloc[0])
    end_px = float(series.iloc[-1])
    if start_px <= 0:
        return None
    return end_px / start_px - 1.0


def _annualized_vol(series: pd.Series, window: int = 30) -> float | None:
    if series is None or len(series) < window + 1:
        return None
    rets = series.pct_change().dropna().tail(window)
    if len(rets) < 5:
        return None
    std = float(rets.std())
    if math.isnan(std):
        return None
    return std * math.sqrt(252)


@with_retries
def fetch_price_metrics(ticker: str, *, as_of: datetime | None = None) -> PriceMetrics:
    """Return a ``PriceMetrics`` snapshot for ``ticker``.

    See module docstring for normalization details.

    Raises
    ------
    InvalidInputError
        If ``ticker`` fails validation.
    NoDataError
        If yfinance returns no price data for the symbol.
    UpstreamAPIError
        For network / HTTP failures talking to Yahoo.
    """
    symbol = validate_ticker(ticker)
    as_of = as_of or datetime.now(timezone.utc)

    try:
        t = yf.Ticker(symbol)
        info: dict[str, Any] = t.info or {}
        hist: pd.DataFrame = t.history(period="1y", auto_adjust=False)
    except Exception as e:  # yfinance lacks a stable public exception hierarchy
        raise UpstreamAPIError(f"yfinance failure for {symbol}: {e}") from e

    current = _f(info.get("currentPrice") or info.get("regularMarketPrice"))
    prev_close = _f(info.get("previousClose") or info.get("regularMarketPreviousClose"))

    close: pd.Series | None = None
    if hist is not None and not hist.empty:
        close = hist["Close"].dropna()
        if current is None and not close.empty:
            current = float(close.iloc[-1])
        if prev_close is None and len(close) >= 2:
            prev_close = float(close.iloc[-2])

    if current is None:
        raise NoDataError(f"No price data returned for {symbol}")

    day_change_pct: float | None = None
    if prev_close not in (None, 0):
        day_change_pct = current / prev_close - 1.0

    returns = ReturnsBundle(
        one_month=_pct_return(close, 30) if close is not None else None,
        three_month=_pct_return(close, 90) if close is not None else None,
        six_month=_pct_return(close, 182) if close is not None else None,
        ytd=_ytd_return(close) if close is not None else None,
        one_year=_pct_return(close, 365) if close is not None else None,
    )

    ma_50 = ma_200 = None
    if close is not None and not close.empty:
        if len(close) >= 50:
            ma_50 = float(close.tail(50).mean())
        if len(close) >= 200:
            ma_200 = float(close.tail(200).mean())

    vol_30 = _annualized_vol(close, 30) if close is not None else None

    next_earnings = None
    et = info.get("earningsTimestamp")
    if et:
        try:
            next_earnings = datetime.fromtimestamp(int(et), tz=timezone.utc).date()
        except (ValueError, TypeError, OSError):
            next_earnings = None

    return PriceMetrics(
        ticker=symbol,
        as_of=as_of,
        currency=str(info.get("currency") or "USD").upper(),
        current_price=current,
        previous_close=prev_close,
        day_change_pct=day_change_pct,
        week_52_high=_f(info.get("fiftyTwoWeekHigh")),
        week_52_low=_f(info.get("fiftyTwoWeekLow")),
        market_cap=_f(info.get("marketCap")),
        pe_ttm=_f(info.get("trailingPE")),
        pe_forward=_f(info.get("forwardPE")),
        eps_ttm=_f(info.get("trailingEps")),
        dividend_yield=_f(info.get("dividendYield")),
        beta=_f(info.get("beta")),
        avg_volume_30d=_f(
            info.get("averageDailyVolume10Day") or info.get("averageVolume")
        ),
        volatility_30d=vol_30,
        moving_avg_50d=ma_50,
        moving_avg_200d=ma_200,
        returns=returns,
        next_earnings_date=next_earnings,
    )


@with_retries
def fetch_price_history(
    ticker: str,
    *,
    period: str = "1y",
    interval: str = "1d",
) -> list[dict]:
    """Return a list of OHLCV bars for ``ticker``.

    Each bar is a plain dict with keys: ``date`` (ISO 8601), ``open``,
    ``high``, ``low``, ``close``, ``adj_close``, ``volume``.

    Raises
    ------
    InvalidInputError
        If ``ticker`` fails validation.
    NoDataError
        If no bars are returned.
    UpstreamAPIError
        For network / HTTP failures.
    """
    symbol = validate_ticker(ticker)
    try:
        hist = yf.Ticker(symbol).history(
            period=period, interval=interval, auto_adjust=False
        )
    except Exception as e:
        raise UpstreamAPIError(f"yfinance history failure for {symbol}: {e}") from e
    if hist is None or hist.empty:
        raise NoDataError(f"No history returned for {symbol}")

    bars: list[dict] = []
    for ts, row in hist.iterrows():
        bars.append(
            {
                "date": pd.Timestamp(ts).to_pydatetime().isoformat(),
                "open": _f(row.get("Open")),
                "high": _f(row.get("High")),
                "low": _f(row.get("Low")),
                "close": _f(row.get("Close")),
                "adj_close": _f(row.get("Adj Close")),
                "volume": _f(row.get("Volume")),
            }
        )
    return bars
