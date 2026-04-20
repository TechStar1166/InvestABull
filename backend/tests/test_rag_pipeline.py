"""Pipeline tests: ChromaStore + ingestion + retrieval with a hash embedder.

Avoids downloading sentence-transformers during tests by injecting a tiny,
deterministic embedding function. Semantic quality is out of scope - we're
verifying plumbing (upsert, filters, citation shape, idempotence).
"""

from __future__ import annotations

import hashlib
from datetime import date

import pytest

chromadb = pytest.importorskip("chromadb")

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings  # noqa: E402

from app.rag.chroma_store import ChromaStore  # noqa: E402
from app.rag.chunking import FilingChunk  # noqa: E402
from app.rag.ingestion import ingest_filing_document  # noqa: E402
from app.rag.retrieval import query_filings  # noqa: E402
from app.tools.sec_filings_tool import FilingDocument  # noqa: E402


class _HashEmbedder(EmbeddingFunction[Documents]):
    """Deterministic 32-dim embedder derived from SHA-256 of the document."""

    def __call__(self, input: Documents) -> Embeddings:  # type: ignore[override]
        vectors: Embeddings = []
        for doc in input:
            digest = hashlib.sha256((doc or "").encode("utf-8")).digest()
            vectors.append([(b - 128) / 128.0 for b in digest[:32]])
        return vectors

    @staticmethod
    def name() -> str:
        return "hash-test-v1"


@pytest.fixture
def store(tmp_path):
    s = ChromaStore(
        persist_dir=tmp_path / "chroma",
        embedding_function=_HashEmbedder(),
        collection_name="sec_10k_test",
    )
    yield s


def _chunks() -> list[FilingChunk]:
    base = dict(
        cik="0000320193",
        accession_number="0000320193-24-000123",
        primary_document_url="https://www.sec.gov/Archives/edgar/data/320193/aapl-10k.htm",
        ticker="AAPL",
        filed_on=date(2024, 11, 1),
        period_of_report=date(2024, 9, 28),
        form_type="10-K",
    )
    return [
        FilingChunk(
            chunk_id=f"{base['accession_number']}:risk_factors:0",
            section="risk_factors",
            chunk_index=0,
            text="Our business is exposed to supply chain concentration in Asia.",
            **base,
        ),
        FilingChunk(
            chunk_id=f"{base['accession_number']}:risk_factors:1",
            section="risk_factors",
            chunk_index=1,
            text="Regulatory scrutiny around the App Store is increasing globally.",
            **base,
        ),
        FilingChunk(
            chunk_id=f"{base['accession_number']}:business_overview:0",
            section="business_overview",
            chunk_index=0,
            text="We design and sell smartphones, computers, wearables, and services.",
            **base,
        ),
    ]


def test_upsert_and_count(store):
    chunks = _chunks()
    assert store.upsert(chunks) == 3
    assert store.count() == 3

    # Idempotent re-ingest doesn't duplicate rows.
    assert store.upsert(chunks) == 3
    assert store.count() == 3


def test_query_returns_citation_ready_chunks(store):
    store.upsert(_chunks())

    results = query_filings(
        store,
        "supply chain risk",
        ticker="AAPL",
        k=3,
    )
    assert results, "expected at least one hit"
    top = results[0]
    assert top.ticker == "AAPL"
    assert top.section in {"risk_factors", "business_overview"}
    assert top.citation.source_name.startswith("SEC 10-K AAPL")
    assert top.citation.identifier == "0000320193-24-000123"
    assert 0.0 <= top.score <= 1.0


def test_query_respects_section_filter(store):
    store.upsert(_chunks())

    results = query_filings(
        store,
        "anything",
        ticker="AAPL",
        sections=["business_overview"],
        k=5,
    )
    assert results
    assert all(r.section == "business_overview" for r in results)


def test_query_rejects_empty_question(store):
    with pytest.raises(ValueError):
        query_filings(store, "   ")


def test_ingest_filing_document_chunks_and_upserts(store):
    doc = FilingDocument(
        ticker="AAPL",
        cik="0000320193",
        accession_number="0000320193-24-000123",
        form_type="10-K",
        filed_on=date(2024, 11, 1),
        period_of_report=date(2024, 9, 28),
        primary_document_url="https://www.sec.gov/demo.htm",
        raw_text=(
            "Item 1. Business\n"
            + ("We design smartphones and services. " * 40)
            + "\n\nItem 1A. Risk Factors\n"
            + ("Supply chain concentration risk. " * 40)
        ),
    )
    result = ingest_filing_document(store, doc)
    assert result.ticker == "AAPL"
    assert result.accession_number == doc.accession_number
    assert result.chunks_ingested >= 2
    assert "risk_factors" in result.sections
    assert "business_overview" in result.sections
    assert store.count() == result.chunks_ingested
