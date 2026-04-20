"""Section-aware chunker for SEC 10-K filings.

Strategy
--------
1. Detect ``Item X[A-C]?.`` headings at line starts.
2. For each heading, keep the **longest** occurrence in the document. This
   trivially filters out table-of-contents entries: the ToC version spans only
   a few hundred characters before the next heading, while the real section
   body runs for thousands of characters.
3. Aggregate items into canonical sections (``business_overview``,
   ``risk_factors``, ``legal_proceedings``, ``mdna``, ``financial_statements``,
   ``other``) so the Filings agent can filter retrieval cleanly.
4. Split each section into overlapping chunks bounded by target character
   counts, preferring paragraph or sentence boundaries.

Chars-per-token is roughly 4 for English 10-K prose, so the defaults
(``target_chars=3200``, ``overlap_chars=480``) land near 800 / 120 tokens and
sit comfortably below the 8k context most embedding models accept.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field

CANONICAL_SECTIONS: tuple[str, ...] = (
    "business_overview",
    "risk_factors",
    "legal_proceedings",
    "mdna",
    "financial_statements",
    "other",
)

_ITEM_TO_SECTION: dict[str, str] = {
    "1": "business_overview",
    "1A": "risk_factors",
    "1B": "other",
    "1C": "other",
    "2": "other",
    "3": "legal_proceedings",
    "4": "other",
    "5": "other",
    "6": "other",
    "7": "mdna",
    "7A": "mdna",
    "8": "financial_statements",
    "9": "other",
    "9A": "other",
    "9B": "other",
}

# Matches 'Item 1.', 'ITEM 1A.', 'Item 7A ' at the start of a (possibly indented) line.
_ITEM_RE = re.compile(r"(?im)^[\s\u00a0]*item\s+(\d{1,2}[a-c]?)\s*\.?\s")


class FilingChunk(BaseModel):
    """A single chunk of a 10-K filing ready for embedding + retrieval."""

    chunk_id: str = Field(
        ...,
        description="Deterministic id '<accession>:<section>:<chunk_index>'.",
    )
    ticker: str | None = None
    cik: str
    accession_number: str
    section: str
    chunk_index: int
    text: str
    primary_document_url: str
    filed_on: date | None = None
    period_of_report: date | None = None
    form_type: str = "10-K"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_sections(text: str) -> dict[str, str]:
    """Return ``{canonical_section: body}`` for the supplied filing text.

    Items that fall outside the canonical map are merged under ``'other'``.
    If no item headings are found, the whole document is returned as
    ``{'other': text}`` (empty input returns ``{}``).
    """
    text = text or ""
    matches = list(_ITEM_RE.finditer(text))
    if not matches:
        stripped = text.strip()
        return {"other": stripped} if stripped else {}

    # (item_key, body) for every heading-to-heading segment
    segments: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        key = m.group(1).upper()
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segments.append((key, text[start:end].strip()))

    # Keep the longest occurrence per item (ToC -> real-content dedupe).
    longest: dict[str, str] = {}
    for key, body in segments:
        if key not in longest or len(body) > len(longest[key]):
            longest[key] = body

    # Aggregate by canonical section. Multiple items may map to the same
    # section (e.g. 7 and 7A both -> mdna); concatenate in item-key order.
    out: dict[str, str] = {}
    for key in sorted(longest, key=_item_sort_key):
        body = longest[key]
        section = _ITEM_TO_SECTION.get(key, "other")
        out[section] = out[section] + "\n\n" + body if section in out else body
    return out


def chunk_text(
    text: str,
    *,
    target_chars: int = 3200,
    overlap_chars: int = 480,
) -> list[str]:
    """Split ``text`` into overlapping chunks at clean boundaries.

    Raises
    ------
    ValueError
        If ``overlap_chars >= target_chars``.
    """
    if overlap_chars >= target_chars:
        raise ValueError("overlap_chars must be smaller than target_chars")
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= target_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + target_chars, n)
        if end < n:
            floor = start + target_chars // 2
            for sep in ("\n\n", "\n", ". "):
                idx = text.rfind(sep, floor, end)
                if idx != -1:
                    end = idx + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def chunk_filing(
    *,
    cik: str,
    accession_number: str,
    raw_text: str,
    primary_document_url: str,
    ticker: str | None = None,
    filed_on: date | None = None,
    period_of_report: date | None = None,
    form_type: str = "10-K",
    target_chars: int = 3200,
    overlap_chars: int = 480,
) -> list[FilingChunk]:
    """Turn a raw filing into a list of ``FilingChunk`` objects."""
    sections = extract_sections(raw_text)
    out: list[FilingChunk] = []
    for section, body in sections.items():
        pieces = chunk_text(body, target_chars=target_chars, overlap_chars=overlap_chars)
        for i, piece in enumerate(pieces):
            out.append(
                FilingChunk(
                    chunk_id=f"{accession_number}:{section}:{i}",
                    ticker=ticker,
                    cik=cik,
                    accession_number=accession_number,
                    section=section,
                    chunk_index=i,
                    text=piece,
                    primary_document_url=primary_document_url,
                    filed_on=filed_on,
                    period_of_report=period_of_report,
                    form_type=form_type,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _item_sort_key(key: str) -> tuple[int, str]:
    """Sort '1' < '1A' < '1B' < '2' < ... < '10'."""
    m = re.match(r"^(\d+)([A-Z]?)$", key)
    if not m:
        return (9999, key)
    return (int(m.group(1)), m.group(2))
