"""Unit tests for app.tools.sec_filings_tool (httpx transport mocked)."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

import app.tools.sec_filings_tool as sec_mod
from app.config import get_settings
from app.tools.base import InvalidInputError, NoDataError
from app.tools.sec_filings_tool import (
    FilingDocument,
    fetch_filing_by_accession,
    fetch_latest_10k,
)

TICKER_MAP = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp."},
}

SUBMISSIONS_AAPL = {
    "filings": {
        "recent": {
            "form": ["10-Q", "10-K", "8-K"],
            "accessionNumber": [
                "0000320193-25-000001",
                "0000320193-24-000123",
                "0000320193-24-000100",
            ],
            "filingDate": ["2025-02-01", "2024-11-01", "2024-10-15"],
            "reportDate": ["2024-12-28", "2024-09-28", "2024-09-01"],
            "primaryDocument": ["aapl-q1.htm", "aapl-10k.htm", "aapl-8k.htm"],
        }
    }
}

INDEX_JSON = {
    "directory": {
        "item": [
            {"name": "primary_doc-index.htm", "type": "index"},
            {"name": "aapl-10k.htm", "type": "10-K"},
            {"name": "exhibit-31.htm", "type": "EX-31"},
        ]
    }
}

FILING_HTML = (
    b"<html><body>"
    b"<script>evil()</script>"
    b"<h1>Item 1A. Risk Factors</h1>"
    b"<p>Our business is subject to intense competition.</p>"
    b"</body></html>"
)


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/files/company_tickers.json"):
        return httpx.Response(200, json=TICKER_MAP)
    if "/submissions/CIK0000320193.json" in url:
        return httpx.Response(200, json=SUBMISSIONS_AAPL)
    if "/Archives/edgar/data/320193/000032019324000123/index.json" in url:
        return httpx.Response(200, json=INDEX_JSON)
    if (
        "/Archives/edgar/data/320193/000032019324000123/aapl-10k.htm" in url
    ):
        return httpx.Response(200, content=FILING_HTML)
    return httpx.Response(404, text=f"unexpected URL: {url}")


@pytest.fixture
def fresh_cache(tmp_path, monkeypatch):
    """Isolate the filing cache directory per-test and reset the ticker cache."""
    monkeypatch.setenv("SEC_FILINGS_CACHE_DIR", str(tmp_path))
    get_settings.cache_clear()
    sec_mod._TICKER_CACHE = None
    yield tmp_path


@pytest.fixture
def patched_client():
    transport = httpx.MockTransport(_handler)

    def fake_client():
        return httpx.Client(
            headers={"User-Agent": "test-agent"},
            transport=transport,
            follow_redirects=True,
        )

    with patch.object(sec_mod, "_http_client", side_effect=fake_client):
        yield


def test_fetch_latest_10k_happy(fresh_cache, patched_client):
    doc = fetch_latest_10k("aapl")

    assert isinstance(doc, FilingDocument)
    assert doc.ticker == "AAPL"
    assert doc.cik == "0000320193"
    assert doc.accession_number == "0000320193-24-000123"
    assert doc.form_type == "10-K"
    assert str(doc.filed_on) == "2024-11-01"
    assert str(doc.period_of_report) == "2024-09-28"
    assert "Risk Factors" in doc.raw_text
    assert "evil" not in doc.raw_text  # <script> stripped

    # Cached to disk
    cached = fresh_cache / "0000320193-24-000123.txt"
    assert cached.exists()


def test_fetch_latest_10k_unknown_ticker(fresh_cache, patched_client):
    with pytest.raises(NoDataError):
        fetch_latest_10k("ZZZZ")


def test_fetch_filing_by_accession_happy(fresh_cache, patched_client):
    doc = fetch_filing_by_accession("0000320193-24-000123")
    assert doc.cik == "0000320193"
    assert doc.ticker is None
    assert doc.form_type == "10-K"
    assert "Risk Factors" in doc.raw_text


def test_fetch_filing_by_accession_bad_format():
    with pytest.raises(InvalidInputError):
        fetch_filing_by_accession("not-an-accession")
