"""Unit tests for app.rag.chunking."""

from __future__ import annotations

from app.rag.chunking import (
    CANONICAL_SECTIONS,
    chunk_filing,
    chunk_text,
    extract_sections,
)


def _fabricate_10k() -> str:
    """Tiny synthetic 10-K with ToC plus real sections."""
    business_body = (
        "We design and sell smartphones, computers, and services. " * 50
    )
    risk_body = (
        "Our business is exposed to supply chain concentration in Asia. "
        "Regulatory scrutiny around the App Store is increasing. "
    ) * 40
    legal_body = (
        "We are party to various legal proceedings arising in the ordinary course. "
    ) * 20
    mdna_body = (
        "Total net sales grew 4% year-over-year driven by Services. " * 60
    )
    market_risk_body = (
        "We are exposed to foreign currency risk across the euro and yen. " * 20
    )
    fs_body = (
        "The accompanying consolidated financial statements were prepared in accordance "
        "with U.S. GAAP. " * 30
    )

    return "\n".join(
        [
            "TABLE OF CONTENTS",
            "Item 1. Business ........................ 3",
            "Item 1A. Risk Factors ................... 10",
            "Item 3. Legal Proceedings ............... 30",
            "Item 7. Management's Discussion ......... 40",
            "Item 7A. Market Risk .................... 50",
            "Item 8. Financial Statements ............ 55",
            "",
            "Item 1. Business",
            business_body,
            "",
            "Item 1A. Risk Factors",
            risk_body,
            "",
            "Item 3. Legal Proceedings",
            legal_body,
            "",
            "Item 7. Management's Discussion and Analysis",
            mdna_body,
            "",
            "Item 7A. Quantitative and Qualitative Disclosures About Market Risk",
            market_risk_body,
            "",
            "Item 8. Financial Statements",
            fs_body,
        ]
    )


def test_extract_sections_dedupes_toc_against_body():
    text = _fabricate_10k()
    sections = extract_sections(text)

    # Canonical buckets we expect, given the synthetic 10-K
    assert "business_overview" in sections
    assert "risk_factors" in sections
    assert "legal_proceedings" in sections
    assert "mdna" in sections
    assert "financial_statements" in sections

    # Every canonical key returned must be in the allowed set.
    for key in sections:
        assert key in CANONICAL_SECTIONS

    # ToC entry for Item 1 is <100 chars; real body is >2k. Dedupe worked.
    assert len(sections["business_overview"]) > 1_000
    assert len(sections["risk_factors"]) > 1_000

    # 7 + 7A were both assigned to mdna and concatenated.
    assert "year-over-year" in sections["mdna"]
    assert "foreign currency risk" in sections["mdna"]


def test_extract_sections_no_headings():
    assert extract_sections("") == {}
    plain = "Just a blob of text without item markers."
    assert extract_sections(plain) == {"other": plain}


def test_chunk_text_boundaries_and_overlap():
    body = ("This is a sentence. " * 500).strip()
    chunks = chunk_text(body, target_chars=1200, overlap_chars=200)

    assert len(chunks) >= 2
    for c in chunks:
        assert c.strip()
        assert len(c) <= 1200 + 50  # some slack for boundary snapping

    # Consecutive chunks should share at least some tail/head text due to overlap.
    first_tail = chunks[0][-100:]
    assert first_tail in chunks[1] or any(w in chunks[1] for w in first_tail.split()[-5:])


def test_chunk_text_short_input_single_chunk():
    assert chunk_text("") == []
    assert chunk_text("short", target_chars=1000) == ["short"]


def test_chunk_filing_produces_stable_ids():
    text = _fabricate_10k()
    chunks = chunk_filing(
        cik="0000320193",
        accession_number="0000320193-24-000123",
        raw_text=text,
        primary_document_url="https://www.sec.gov/demo.htm",
        ticker="AAPL",
    )

    assert chunks, "expected at least one chunk"
    # Ids must be deterministic and unique.
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    for c in chunks:
        assert c.chunk_id == f"{c.accession_number}:{c.section}:{c.chunk_index}"
        assert c.ticker == "AAPL"
        assert c.section in CANONICAL_SECTIONS
