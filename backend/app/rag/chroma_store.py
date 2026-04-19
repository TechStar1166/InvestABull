"""ChromaDB persistent vector-store wrapper for SEC filings.

Notes
-----
* Chroma metadata values must be ``str | int | float | bool``. ``None`` and
  ``date`` values are filtered / coerced to strings before upsert.
* The collection is configured for cosine distance; callers convert the raw
  distance into a [0, 1] similarity score in ``app.rag.retrieval``.
* Ids are the deterministic ``FilingChunk.chunk_id`` so ``upsert`` is
  idempotent across re-ingestions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.types import EmbeddingFunction

from app.rag.chunking import FilingChunk

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "sec_10k"


def _default_embedding_function(model_name: str) -> EmbeddingFunction:
    """Build the production embedder. Imported lazily so tests that inject a
    stub don't need ``sentence-transformers`` / ``torch`` on disk."""
    from chromadb.utils import embedding_functions

    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model_name)


class ChromaStore:
    """Thin, typed facade over a Chroma ``PersistentClient`` collection."""

    def __init__(
        self,
        persist_dir: Path | str,
        *,
        embedding_function: EmbeddingFunction | None = None,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        persist_dir = Path(persist_dir)
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        ef = embedding_function or _default_embedding_function(embedding_model)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def collection(self):  # noqa: D401 - trivial property
        """Underlying Chroma collection (escape hatch for advanced callers)."""
        return self._collection

    def count(self) -> int:
        return self._collection.count()

    def upsert(self, chunks: list[FilingChunk]) -> int:
        """Insert-or-update a batch of chunks. Returns the number upserted."""
        if not chunks:
            return 0
        ids = [c.chunk_id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [self._metadata(c) for c in chunks]
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(chunks)

    def query(
        self,
        text: str,
        *,
        where: dict | None = None,
        k: int = 6,
    ) -> list[dict]:
        """Return up to ``k`` raw hits.

        Each hit is a dict with keys ``chunk_id``, ``text``, ``metadata``, and
        ``distance`` (Chroma cosine distance, lower = closer).
        """
        if not text or not isinstance(text, str):
            raise ValueError("query text must be a non-empty string")
        res = self._collection.query(
            query_texts=[text],
            n_results=max(1, int(k)),
            where=where,
        )
        hits: list[dict] = []
        ids = (res or {}).get("ids") or [[]]
        if not ids or not ids[0]:
            return hits
        docs = res.get("documents") or [[]]
        metas = res.get("metadatas") or [[]]
        dists = res.get("distances") or [[]]
        for i, chunk_id in enumerate(ids[0]):
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "text": docs[0][i] if i < len(docs[0]) else "",
                    "metadata": (metas[0][i] if i < len(metas[0]) else {}) or {},
                    "distance": float(dists[0][i]) if i < len(dists[0]) else 0.0,
                }
            )
        return hits

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _metadata(chunk: FilingChunk) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "cik": chunk.cik,
            "accession_number": chunk.accession_number,
            "section": chunk.section,
            "chunk_index": chunk.chunk_index,
            "primary_document_url": chunk.primary_document_url,
            "form_type": chunk.form_type,
        }
        if chunk.ticker:
            meta["ticker"] = chunk.ticker
        if chunk.filed_on is not None:
            meta["filed_on"] = chunk.filed_on.isoformat()
        if chunk.period_of_report is not None:
            meta["period_of_report"] = chunk.period_of_report.isoformat()
        return meta
