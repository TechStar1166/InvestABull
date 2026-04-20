"""Unit tests for app.tools.fred_tool (fredapi patched)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.config import get_settings
from app.schemas.common import TrendDirection
from app.schemas.macro import MacroIndicator
from app.tools.base import InvalidInputError, NoDataError
from app.tools.fred_tool import (
    clear_macro_cache,
    fetch_indicator,
    fetch_macro_bundle,
)


@pytest.fixture(autouse=True)
def _reset_macro_cache():
    """Every test starts with empty bundle + series-info caches."""
    clear_macro_cache()
    yield
    clear_macro_cache()


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


def _dispatch_client(
    ok_series: pd.Series, ok_info: pd.Series, bad_ids: set[str]
) -> MagicMock:
    """Build a fake client whose outcome depends on the series_id argument.

    Using the id (not call order) makes the test deterministic regardless of
    whether ``fetch_macro_bundle`` runs sequentially or in a thread pool.
    """
    client = MagicMock()

    def _get_series(sid: str) -> pd.Series:
        if sid in bad_ids:
            raise ValueError(f"missing {sid}")
        return ok_series

    def _get_info(sid: str) -> pd.Series:
        if sid in bad_ids:
            raise ValueError(f"missing {sid}")
        return ok_info

    client.get_series.side_effect = _get_series
    client.get_series_info.side_effect = _get_info
    return client


def test_fetch_macro_bundle_skips_failures_and_preserves_input_order():
    ok_series = _monthly_series()
    ok_info = _info("Ok", "Units", "Monthly")
    client = _dispatch_client(ok_series, ok_info, bad_ids={"B_BAD"})

    with patch("app.tools.fred_tool._fred_client", return_value=client):
        out = fetch_macro_bundle(("A", "B_BAD", "C"))

    assert [i.series_id for i in out] == ["A", "C"]


def test_fetch_macro_bundle_parallel_path_returns_input_order(monkeypatch):
    """With multiple workers, results must still come back in input order."""
    ok_series = _monthly_series()
    ok_info = _info("Ok", "Units", "Monthly")
    client = _dispatch_client(ok_series, ok_info, bad_ids=set())

    settings = get_settings()
    monkeypatch.setattr(settings, "fred_max_workers", 4)

    with patch("app.tools.fred_tool._fred_client", return_value=client):
        out = fetch_macro_bundle(("X1", "X2", "X3", "X4", "X5"))

    assert [i.series_id for i in out] == ["X1", "X2", "X3", "X4", "X5"]


def test_fetch_macro_bundle_sequential_when_workers_is_one(monkeypatch):
    ok_series = _monthly_series()
    ok_info = _info("Ok", "Units", "Monthly")
    client = _dispatch_client(ok_series, ok_info, bad_ids=set())

    settings = get_settings()
    monkeypatch.setattr(settings, "fred_max_workers", 1)

    with patch("app.tools.fred_tool._fred_client", return_value=client):
        out = fetch_macro_bundle(("A", "B", "C"))

    assert [i.series_id for i in out] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# TTL caches
# ---------------------------------------------------------------------------


def test_bundle_cache_hit_avoids_second_fetch(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "fred_bundle_cache_ttl_seconds", 3600)

    ok_series = _monthly_series()
    ok_info = _info("Ok", "Units", "Monthly")
    client = _dispatch_client(ok_series, ok_info, bad_ids=set())

    with patch("app.tools.fred_tool._fred_client", return_value=client):
        first = fetch_macro_bundle(("A", "B"))
        call_count_after_first = client.get_series.call_count
        second = fetch_macro_bundle(("A", "B"))

    assert [i.series_id for i in first] == ["A", "B"]
    assert [i.series_id for i in second] == ["A", "B"]
    assert client.get_series.call_count == call_count_after_first, \
        "second call must not hit FRED"


def test_bundle_cache_key_differentiates_series_tuples(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "fred_bundle_cache_ttl_seconds", 3600)

    ok_series = _monthly_series()
    ok_info = _info("Ok", "Units", "Monthly")
    client = _dispatch_client(ok_series, ok_info, bad_ids=set())

    with patch("app.tools.fred_tool._fred_client", return_value=client):
        fetch_macro_bundle(("A", "B"))
        before = client.get_series.call_count
        fetch_macro_bundle(("A", "C"))  # different tuple -> different key
        after = client.get_series.call_count

    assert after > before, "different tuple must trigger a real fetch"


def test_bundle_cache_disabled_when_ttl_zero(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "fred_bundle_cache_ttl_seconds", 0)

    ok_series = _monthly_series()
    ok_info = _info("Ok", "Units", "Monthly")
    client = _dispatch_client(ok_series, ok_info, bad_ids=set())

    with patch("app.tools.fred_tool._fred_client", return_value=client):
        fetch_macro_bundle(("A",))
        fetch_macro_bundle(("A",))

    # Two real fetches, one per call
    assert client.get_series.call_count == 2


def test_bundle_cache_expires(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "fred_bundle_cache_ttl_seconds", 1)

    ok_series = _monthly_series()
    ok_info = _info("Ok", "Units", "Monthly")
    client = _dispatch_client(ok_series, ok_info, bad_ids=set())

    fake_now = {"t": 1000.0}

    def _monotonic():
        return fake_now["t"]

    monkeypatch.setattr("app.tools.fred_tool.time.monotonic", _monotonic)

    with patch("app.tools.fred_tool._fred_client", return_value=client):
        fetch_macro_bundle(("A",))
        fake_now["t"] += 60  # far past TTL
        fetch_macro_bundle(("A",))

    assert client.get_series.call_count == 2


def test_series_info_cache_avoids_second_metadata_call(monkeypatch):
    """get_series_info is cached independently with a longer TTL."""
    settings = get_settings()
    # Disable the bundle cache so we're isolating the info cache.
    monkeypatch.setattr(settings, "fred_bundle_cache_ttl_seconds", 0)
    monkeypatch.setattr(settings, "fred_series_info_cache_ttl_seconds", 3600)

    ok_series = _monthly_series()
    ok_info = _info("Ok", "Units", "Monthly")
    client = _dispatch_client(ok_series, ok_info, bad_ids=set())

    with patch("app.tools.fred_tool._fred_client", return_value=client):
        fetch_macro_bundle(("A",))
        info_calls_after_first = client.get_series_info.call_count
        fetch_macro_bundle(("A",))

    # Observations are re-fetched, but metadata should come from cache.
    assert client.get_series.call_count == 2
    assert client.get_series_info.call_count == info_calls_after_first
