"""SEC EDGAR filing retrieval.

Raw retrieval only. Chunking, embedding, and semantic retrieval live in
``app.rag`` (Phase 3) to preserve the "raw retrieval vs. agent reasoning"
separation demanded by the architecture.

Implementation notes
--------------------
* We hit the SEC's JSON / archive endpoints directly via ``httpx`` so we can
  reuse a single client with the mandatory ``User-Agent`` header and control
  retries. ``sec-edgar-downloader`` is intentionally avoided - it writes to
  disk eagerly and hides the response we want to clean.
* The ticker -> CIK map is fetched once per process and cached in memory.
* Cleaned plaintext is persisted under ``SEC_FILINGS_CACHE_DIR`` so the
  ChromaDB ingestion pipeline (Phase 3) can re-read without round-tripping.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.tools.base import (
    InvalidInputError,
    NoDataError,
    RateLimitError,
    UpstreamAPIError,
    validate_ticker,
    with_retries,
)

logger = logging.getLogger(__name__)


class FilingDocument(BaseModel):
    """Raw 10-K (or similar) filing as pulled from EDGAR.

    Kept separate from ``FilingsFindings`` so tools never mix raw retrieval
    with agent interpretation.
    """

    ticker: str | None = Field(
        default=None,
        description="Ticker, if known. Unknown when fetching purely by accession.",
    )
    cik: str = Field(..., description="Central Index Key, zero-padded 10 digits.")
    accession_number: str = Field(..., description="EDGAR accession, e.g. '0000320193-24-000123'.")
    form_type: str = Field(default="10-K")
    filed_on: date | None = None
    period_of_report: date | None = None
    primary_document_url: str
    raw_text: str = Field(..., description="Cleaned plain-text body of the filing.")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"
_ACCESSION_RE = re.compile(r"^(\d{10})-(\d{2})-(\d{6})$")

# Cached across calls in the same process; tests may null it out.
_TICKER_CACHE: dict[str, tuple[str, str]] | None = None


def _http_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        headers={
            "User-Agent": settings.sec_edgar_user_agent,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        },
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
    )


def _raise_for_status(r: httpx.Response, ctx: str) -> None:
    if r.status_code == 429:
        raise RateLimitError(f"SEC EDGAR rate-limited ({ctx})")
    if r.status_code >= 400:
        raise UpstreamAPIError(
            f"SEC EDGAR {r.status_code} {ctx}: {r.text[:200]}"
        )


def _load_ticker_map(client: httpx.Client) -> dict[str, tuple[str, str]]:
    global _TICKER_CACHE
    if _TICKER_CACHE is not None:
        return _TICKER_CACHE
    r = client.get(_TICKER_MAP_URL)
    _raise_for_status(r, "ticker map")
    try:
        payload = r.json()
    except json.JSONDecodeError as e:
        raise UpstreamAPIError(f"SEC ticker map invalid JSON: {e}") from e

    mp: dict[str, tuple[str, str]] = {}
    for row in payload.values():
        try:
            t = str(row["ticker"]).upper()
            cik10 = str(row["cik_str"]).zfill(10)
        except (KeyError, TypeError):
            continue
        title = str(row.get("title", ""))
        mp[t] = (cik10, title)
    _TICKER_CACHE = mp
    return mp


def _lookup_cik(client: httpx.Client, ticker: str) -> tuple[str, str]:
    mp = _load_ticker_map(client)
    if ticker not in mp:
        raise NoDataError(f"No CIK registered with the SEC for ticker {ticker!r}")
    return mp[ticker]


# ---------------------------------------------------------------------------
# HTML cleanup
# ---------------------------------------------------------------------------


def _clean_html(raw: bytes | str) -> str:
    html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def _clean_plain(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def _cache_path(settings: Settings, accession: str) -> Path:
    d = Path(settings.sec_filings_cache_dir)
    d.mkdir(parents=True, exist_ok=True)
    safe = accession.replace("/", "_")
    return d / f"{safe}.txt"


def _fetch_primary_document(
    client: httpx.Client,
    cik10: str,
    accession: str,
    primary_document: str,
) -> tuple[str, str]:
    """Download the primary document, clean it, cache to disk.

    Returns ``(cleaned_text, primary_url)``.
    """
    settings = get_settings()
    cache = _cache_path(settings, accession)
    cik_int = int(cik10)
    acc_nodash = accession.replace("-", "")
    primary_url = _ARCHIVE_URL.format(
        cik_int=cik_int, acc_nodash=acc_nodash, doc=primary_document
    )

    if cache.exists():
        return cache.read_text(encoding="utf-8"), primary_url

    r = client.get(primary_url)
    _raise_for_status(r, f"filing {accession}")
    if primary_document.lower().endswith((".htm", ".html")):
        text = _clean_html(r.content)
    else:
        text = _clean_plain(r.text)

    cache.write_text(text, encoding="utf-8")
    return text, primary_url


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _select_latest_10k(recent: dict[str, Any]) -> int:
    forms = recent.get("form") or []
    for i, form in enumerate(forms):
        if form == "10-K":
            return i
    raise NoDataError("No 10-K found in recent submissions")


@with_retries
def fetch_latest_10k(ticker: str) -> FilingDocument:
    """Return the most recent 10-K for ``ticker``.

    Raises
    ------
    InvalidInputError
        If ``ticker`` fails validation.
    NoDataError
        If the company has no 10-K on file.
    UpstreamAPIError / RateLimitError
        For EDGAR HTTP failures.
    """
    symbol = validate_ticker(ticker)
    with _http_client() as client:
        cik10, _title = _lookup_cik(client, symbol)
        r = client.get(_SUBMISSIONS_URL.format(cik10=cik10))
        _raise_for_status(r, f"submissions for {symbol}")
        try:
            data = r.json()
        except json.JSONDecodeError as e:
            raise UpstreamAPIError(f"SEC submissions invalid JSON: {e}") from e

        recent = (data.get("filings") or {}).get("recent") or {}
        idx = _select_latest_10k(recent)

        accession = recent["accessionNumber"][idx]
        filed_on = _safe_date(recent.get("filingDate", [None])[idx])
        period_of_report = _safe_date(recent.get("reportDate", [None])[idx])
        primary_doc = recent["primaryDocument"][idx]

        text, primary_url = _fetch_primary_document(
            client, cik10, accession, primary_doc
        )

    return FilingDocument(
        ticker=symbol,
        cik=cik10,
        accession_number=accession,
        form_type="10-K",
        filed_on=filed_on,
        period_of_report=period_of_report,
        primary_document_url=primary_url,
        raw_text=text,
    )


@with_retries
def fetch_filing_by_accession(accession_number: str) -> FilingDocument:
    """Fetch an arbitrary filing by its EDGAR accession number.

    The CIK is parsed from the accession; the primary document is discovered
    from the filing's ``index.json`` directory listing.
    """
    if not isinstance(accession_number, str) or not accession_number.strip():
        raise InvalidInputError("accession_number must be a non-empty string")

    acc = accession_number.strip()
    m = _ACCESSION_RE.match(acc)
    if not m:
        raise InvalidInputError(
            f"Invalid accession format: {acc!r} (expected NNNNNNNNNN-NN-NNNNNN)"
        )
    cik10 = m.group(1)
    cik_int = int(cik10)
    acc_nodash = acc.replace("-", "")

    with _http_client() as client:
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/index.json"
        )
        r = client.get(index_url)
        _raise_for_status(r, f"index {acc}")
        try:
            idx_data = r.json()
        except json.JSONDecodeError as e:
            raise UpstreamAPIError(f"Accession index invalid JSON: {e}") from e

        items = (idx_data.get("directory") or {}).get("item") or []
        primary_doc: str | None = None
        form_type: str | None = None
        for item in items:
            name = str(item.get("name", ""))
            if name.lower().endswith((".htm", ".html")) and "index" not in name.lower():
                primary_doc = name
                form_type = item.get("type") or None
                break
        if not primary_doc:
            raise NoDataError(f"No primary HTML document found in {acc}")

        text, primary_url = _fetch_primary_document(client, cik10, acc, primary_doc)

    return FilingDocument(
        ticker=None,
        cik=cik10,
        accession_number=acc,
        form_type=form_type or "UNKNOWN",
        filed_on=None,
        period_of_report=None,
        primary_document_url=primary_url,
        raw_text=text,
    )


def _safe_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
