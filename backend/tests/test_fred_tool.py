"""Unit tests for app.tools.fred_tool (fredapi patched)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.schemas.common import TrendDirection
from app.schemas.macro import MacroIndicator
from app.tools.base import InvalidInputError, NoDataError
from app.tools.fred_tool import fetch_indicator, fetch_macro_bundle


def _monthly_series(n: int = 60, start: float = 200.0, step: float = 1.0) -> pd.Series:
    idx = pd.date_range(end="2026-04-01", periods=n, freq="MS")
    return pd.Series([start + i * step for i in range(n)], index=idx, dtype=float)


def _info(title: str, units: str, frequency: str) -> pd.Series:
    return pd.Series({"title": title, "units": units, "frequency": frequency})


def _fake_client(series: pd.Series, info: pd.Series) -> MagicMock:
    fake = MagicMock()
    fake.get_series.return_value = series
    fake.get_series_info.return_value = info
    return fake


def test_fetch_indicator_happy_path():
    series = _monthly_series()
    info = _info("CPI for All Urban Consumers", "Index 1982-1984=100", "Monthly")
    client = _fake_client(series, info)

    with patch("app.tools.fred_tool._fred_client", return_value=client):
        out = fetch_indicator("cpiaucsl")

    assert isinstance(out, MacroIndicator)
    assert out.series_id == "CPIAUCSL"
    assert out.name.startswith("CPI")
    assert out.unit == "Index 1982-1984=100"
    assert out.frequency == "Monthly"
    assert out.latest_value == series.iloc[-1]
    assert out.prior_value == series.iloc[-2]
    assert out.yoy_change is not None and out.yoy_change > 0
    assert out.trend in (TrendDirection.UP, TrendDirection.FLAT, TrendDirection.DOWN)
    assert str(out.citation.url).startswith("https://fred.stlouisfed.org/series/CPIAUCSL")


def test_fetch_indicator_bad_input():
    with pytest.raises(InvalidInputError):
        fetch_indicator("")


def test_fetch_indicator_unknown_series_is_no_data():
    client = MagicMock()
    client.get_series.side_effect = ValueError("Bad Request. 400 (series not found)")
    client.get_series_info.side_effect = ValueError("Bad Request. 400 (series not found)")

    with patch("app.tools.fred_tool._fred_client", return_value=client):
        with pytest.raises(NoDataError):
            fetch_indicator("NOPE")


def test_fetch_macro_bundle_skips_failures():
    ok_series = _monthly_series()
    ok_info = _info("Ok", "Units", "Monthly")

    call_count = {"n": 0}

    def make_client():
        call_count["n"] += 1
        client = MagicMock()
        if call_count["n"] == 2:
            client.get_series.side_effect = ValueError("missing")
            client.get_series_info.side_effect = ValueError("missing")
        else:
            client.get_series.return_value = ok_series
            client.get_series_info.return_value = ok_info
        return client

    with patch("app.tools.fred_tool._fred_client", side_effect=make_client):
        out = fetch_macro_bundle(("A", "B_BAD", "C"))

    assert len(out) == 2
    assert {i.series_id for i in out} == {"A", "C"}
