"""SEC 10-K ingestion + ChromaDB retrieval pipeline.

Submodules:
    chunking    - Section-aware 10-K chunking + ``FilingChunk`` model.
    chroma_store - Typed wrapper around a persistent Chroma collection.
    ingestion   - Orchestrates fetch -> chunk -> upsert.
    retrieval   - Semantic queries that return citation-ready chunks.
"""

from app.rag.chunking import (
    CANONICAL_SECTIONS,
    FilingChunk,
    chunk_filing,
    chunk_text,
    extract_sections,
)
from app.rag.chroma_store import DEFAULT_COLLECTION, ChromaStore
from app.rag.ingestion import IngestResult, ingest_filing_document, ingest_latest_10k
from app.rag.retrieval import RetrievedChunk, query_filings

__all__ = [
    "CANONICAL_SECTIONS",
    "ChromaStore",
    "DEFAULT_COLLECTION",
    "FilingChunk",
    "IngestResult",
    "RetrievedChunk",
    "chunk_filing",
    "chunk_text",
    "extract_sections",
    "ingest_filing_document",
    "ingest_latest_10k",
    "query_filings",
]
