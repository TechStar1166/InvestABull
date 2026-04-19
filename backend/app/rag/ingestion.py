"""Orchestrate ``FilingDocument`` -> chunks -> ChromaDB upsert.

Keeps retrieval logic completely out of this module so the "raw retrieval vs.
agent reasoning" split stays clean.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.rag.chroma_store import ChromaStore
from app.rag.chunking import FilingChunk, chunk_filing
from app.tools.sec_filings_tool import FilingDocument, fetch_latest_10k

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    ticker: str
    accession_number: str
    chunks_ingested: int
    sections: list[str]


def _chunks_from_document(doc: FilingDocument) -> list[FilingChunk]:
    return chunk_filing(
        cik=doc.cik,
        accession_number=doc.accession_number,
        raw_text=doc.raw_text,
        primary_document_url=doc.primary_document_url,
        ticker=doc.ticker,
        filed_on=doc.filed_on,
        period_of_report=doc.period_of_report,
        form_type=doc.form_type,
    )


def ingest_filing_document(store: ChromaStore, doc: FilingDocument) -> IngestResult:
    """Chunk + upsert a pre-fetched filing.

    Idempotent: re-running with the same document just updates existing rows
    in place (chunk ids are deterministic).
    """
    chunks = _chunks_from_document(doc)
    n = store.upsert(chunks)
    sections = sorted({c.section for c in chunks})
    logger.info(
        "ingested %d chunks from %s (%s) across sections %s",
        n,
        doc.ticker or "?",
        doc.accession_number,
        sections,
    )
    return IngestResult(
        ticker=doc.ticker or "",
        accession_number=doc.accession_number,
        chunks_ingested=n,
        sections=sections,
    )


def ingest_latest_10k(ticker: str, store: ChromaStore) -> IngestResult:
    """Fetch the latest 10-K for ``ticker`` and ingest it."""
    doc = fetch_latest_10k(ticker)
    return ingest_filing_document(store, doc)
