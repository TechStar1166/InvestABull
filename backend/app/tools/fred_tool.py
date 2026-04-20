"""FRED (Federal Reserve Economic Data) tool implementation.

Returns strictly-typed :class:`~app.schemas.macro.MacroIndicator` objects.
Sentiment / regime inference is an agent concern; at the tool layer we only
emit raw observations plus a conservative ``trend`` tag and a YoY pct change.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# ---------------------------------------------------------------------------
# In-memory TTL caches
#
# FRED publishes most series on daily / weekly / monthly cadence, so the
# hot-path request rarely sees fresher data than what was fetched minutes
# ago. Two caches:
#
#   * ``_bundle_cache``        - final list[MacroIndicator] for a tuple of
#                                 series ids. Hours-long TTL is safe and
#                                 wipes most macro latency end to end.
#   * ``_series_info_cache``   - per-series metadata (title / units / freq).
#                                 Metadata almost never changes; 24h default
#                                 removes one HTTP round-trip per indicator
#                                 even when the observations are re-fetched.
#
# Thread-safe via separate locks so multiple pipeline threads don't stall
# each other.
# ---------------------------------------------------------------------------


_bundle_cache: dict[tuple[str, ...], tuple[float, list[MacroIndicator]]] = {}
_bundle_cache_lock = threading.Lock()

_series_info_cache: dict[str, tuple[float, Any]] = {}
_series_info_cache_lock = threading.Lock()


def _bundle_cache_get(
    key: tuple[str, ...], ttl: int
) -> list[MacroIndicator] | None:
    if ttl <= 0:
        return None
    now = time.monotonic()
    with _bundle_cache_lock:
        entry = _bundle_cache.get(key)
        if not entry:
            return None
        ts, items = entry
        if now - ts > ttl:
            _bundle_cache.pop(key, None)
            return None
        return list(items)


def _bundle_cache_put(key: tuple[str, ...], items: list[MacroIndicator]) -> None:
    with _bundle_cache_lock:
        _bundle_cache[key] = (time.monotonic(), list(items))


def _info_cache_get(series_id: str, ttl: int) -> Any | None:
    if ttl <= 0:
        return None
    now = time.monotonic()
    with _series_info_cache_lock:
        entry = _series_info_cache.get(series_id)
        if not entry:
            return None
        ts, info = entry
        if now - ts > ttl:
            _series_info_cache.pop(series_id, None)
            return None
        return info


def _info_cache_put(series_id: str, info: Any) -> None:
    with _series_info_cache_lock:
        _series_info_cache[series_id] = (time.monotonic(), info)


def clear_macro_cache() -> None:
    """Drop all FRED caches (bundle + series-info). Used by tests and manual refresh."""
    with _bundle_cache_lock:
        _bundle_cache.clear()
    with _series_info_cache_lock:
        _series_info_cache.clear()

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

    settings = get_settings()
    fred = _fred_client()
    try:
        raw_series = fred.get_series(sid)
        info = _info_cache_get(sid, settings.fred_series_info_cache_ttl_seconds)
        if info is None:
            info = fred.get_series_info(sid)
            _info_cache_put(sid, info)
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
    *,
    max_workers: int | None = None,
    use_cache: bool = True,
) -> list[MacroIndicator]:
    """Fetch several FRED indicators concurrently.

    Each ``fetch_indicator`` call issues two network round-trips
    (observations + metadata); doing them sequentially means one slow series
    stalls the whole Macro domain. We fan out into a thread pool (IO-bound,
    so threads parallelize cleanly) and return results in **input order** so
    callers / tests can rely on deterministic ordering.

    Results for the full tuple of ``series_ids`` are memoised in the
    in-process bundle cache keyed on that tuple, so repeat requests inside
    ``FRED_BUNDLE_CACHE_TTL_SECONDS`` bypass the network entirely. Pass
    ``use_cache=False`` (or set the TTL to 0) to force a refresh.

    Per-series failures are logged and that series is dropped from the
    output; callers can detect missing ids via
    ``len(result) < len(series_ids)`` and surface them on the agent envelope
    as ``raw_data_notes``.
    """
    settings = get_settings()
    key = tuple(str(s).strip().upper() for s in series_ids if str(s).strip())
    if not key:
        return []

    if use_cache:
        cached = _bundle_cache_get(key, settings.fred_bundle_cache_ttl_seconds)
        if cached is not None:
            logger.debug("macro bundle cache hit for %s", key)
            return cached

    workers = max(1, int(max_workers if max_workers is not None else settings.fred_max_workers))
    results: dict[str, MacroIndicator] = {}

    if workers == 1 or len(key) == 1:
        # Sequential path - useful for tests / debugging and avoids the
        # ThreadPoolExecutor setup cost for a single indicator.
        for sid in key:
            try:
                results[sid] = fetch_indicator(sid)
            except (NoDataError, UpstreamAPIError, InvalidInputError) as e:
                logger.warning("FRED series %s skipped: %s", sid, e)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fred") as pool:
            futures = {pool.submit(fetch_indicator, sid): sid for sid in key}
            for fut in as_completed(futures):
                sid = futures[fut]
                try:
                    results[sid] = fut.result()
                except (NoDataError, UpstreamAPIError, InvalidInputError) as e:
                    logger.warning("FRED series %s skipped: %s", sid, e)

    ordered = [results[sid] for sid in key if sid in results]
    if use_cache and ordered:
        _bundle_cache_put(key, ordered)
    return ordered
