"""Unit tests for app.tools.yfinance_tool (yfinance patched)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.schemas.price import PriceMetrics
from app.tools.base import InvalidInputError, NoDataError
from app.tools.yfinance_tool import fetch_price_history, fetch_price_metrics


def _make_hist(days: int = 320) -> pd.DataFrame:
    idx = pd.date_range(end="2026-04-17", periods=days, freq="B", tz="UTC")
    close = pd.Series(
        [100.0 + i * 0.5 for i in range(days)],
        index=idx,
        dtype=float,
    )
    return pd.DataFrame(
        {
            "Open": close - 0.25,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Adj Close": close,
            "Volume": [1_000_000.0] * days,
        },
        index=idx,
    )


def test_fetch_price_metrics_happy_path():
    fake = MagicMock()
    fake.info = {
        "currentPrice": 210.0,
        "previousClose": 208.0,
        "fiftyTwoWeekHigh": 220.0,
        "fiftyTwoWeekLow": 150.0,
        "marketCap": 3_000_000_000_000,
        "trailingPE": 30.0,
        "forwardPE": 28.0,
        "trailingEps": 6.5,
        "dividendYield": 0.004,
        "beta": 1.2,
        "averageDailyVolume10Day": 50_000_000,
        "currency": "usd",
    }
    fake.history.return_value = _make_hist()

    with patch("app.tools.yfinance_tool.yf.Ticker", return_value=fake):
        out = fetch_price_metrics("  aapl ")

    assert isinstance(out, PriceMetrics)
    assert out.ticker == "AAPL"
    assert out.currency == "USD"
    assert out.current_price == 210.0
    assert out.previous_close == 208.0
    assert out.day_change_pct == pytest.approx(210.0 / 208.0 - 1.0, rel=1e-6)
    assert out.pe_ttm == 30.0
    assert out.dividend_yield == 0.004
    assert out.moving_avg_50d is not None and out.moving_avg_200d is not None
    assert out.returns.one_year is not None
    assert out.returns.ytd is not None
    assert out.volatility_30d is not None


def test_fetch_price_metrics_falls_back_to_history_when_info_empty():
    fake = MagicMock()
    fake.info = {}
    fake.history.return_value = _make_hist(days=60)

    with patch("app.tools.yfinance_tool.yf.Ticker", return_value=fake):
        out = fetch_price_metrics("MSFT")

    assert out.current_price is not None
    assert out.previous_close is not None
    assert out.day_change_pct is not None


def test_fetch_price_metrics_no_data():
    fake = MagicMock()
    fake.info = {}
    fake.history.return_value = pd.DataFrame()

    with patch("app.tools.yfinance_tool.yf.Ticker", return_value=fake):
        with pytest.raises(NoDataError):
            fetch_price_metrics("ZZZZ")


def test_fetch_price_metrics_rejects_bad_ticker():
    with pytest.raises(InvalidInputError):
        fetch_price_metrics("!!!not-a-ticker")


def test_fetch_price_history_returns_bars():
    fake = MagicMock()
    fake.history.return_value = _make_hist(days=30)

    with patch("app.tools.yfinance_tool.yf.Ticker", return_value=fake):
        bars = fetch_price_history("AAPL", period="1mo")

    assert len(bars) == 30
    sample = bars[0]
    assert {"date", "open", "high", "low", "close", "adj_close", "volume"} <= sample.keys()
    assert isinstance(sample["date"], str)
