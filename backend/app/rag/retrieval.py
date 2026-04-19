"""Typed semantic query API over the SEC 10-K ChromaDB store.

The Filings specialist agent (Phase 4) only ever calls ``query_filings``, so
this is the sole surface that turns raw Chroma hits into citation-ready
Pydantic objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from pydantic import BaseModel, Field

from app.rag.chroma_store import ChromaStore
from app.schemas.common import SourceCitation


class RetrievedChunk(BaseModel):
    """A single hit returned to the Filings agent."""

    text: str
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Cosine similarity in [0, 1]; 1 = closest to the query.",
    )
    chunk_id: str
    section: str | None = None
    accession_number: str | None = None
    ticker: str | None = None
    metadata: dict = Field(default_factory=dict)
    citation: SourceCitation


def query_filings(
    store: ChromaStore,
    question: str,
    *,
    ticker: str | None = None,
    sections: Iterable[str] | None = None,
    accession_number: str | None = None,
    k: int = 6,
) -> list[RetrievedChunk]:
    """Run a semantic query over the SEC 10-K store.

    Parameters
    ----------
    store:
        A ``ChromaStore`` instance.
    question:
        Natural-language query.
    ticker, sections, accession_number:
        Optional metadata filters (AND-combined).
    k:
        Number of top hits to return.

    Raises
    ------
    ValueError
        If ``question`` is empty.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")

    where = _build_where(ticker, sections, accession_number)
    hits = store.query(question, where=where, k=k)
    now = datetime.now(timezone.utc)

    out: list[RetrievedChunk] = []
    for h in hits:
        md = h.get("metadata") or {}
        distance = float(h.get("distance") or 0.0)
        # Chroma cosine distance runs in [0, 2]; clamp a 1-distance similarity
        # into [0, 1] for a coordinator-friendly confidence proxy.
        score = max(0.0, min(1.0, 1.0 - distance))
        citation = SourceCitation(
            source_name=_citation_name(md),
            url=md.get("primary_document_url") or None,
            identifier=md.get("accession_number"),
            snippet=h["text"][:800],
            retrieved_at=now,
        )
        out.append(
            RetrievedChunk(
                text=h["text"],
                score=score,
                chunk_id=h["chunk_id"],
                section=md.get("section"),
                accession_number=md.get("accession_number"),
                ticker=md.get("ticker"),
                metadata=md,
                citation=citation,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_where(
    ticker: str | None,
    sections: Iterable[str] | None,
    accession_number: str | None,
) -> dict | None:
    clauses: list[dict] = []
    if ticker:
        clauses.append({"ticker": ticker.upper()})
    if sections is not None:
        section_list = [s for s in sections if s]
        if len(section_list) == 1:
            clauses.append({"section": section_list[0]})
        elif section_list:
            clauses.append({"section": {"$in": section_list}})
    if accession_number:
        clauses.append({"accession_number": accession_number})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _citation_name(md: dict) -> str:
    ticker = md.get("ticker") or "?"
    form = md.get("form_type") or "10-K"
    period = md.get("period_of_report") or md.get("filed_on") or ""
    section = md.get("section") or ""
    parts = [f"SEC {form} {ticker}"]
    if period:
        parts.append(str(period))
    if section:
        parts.append(section)
    return " | ".join(parts)
