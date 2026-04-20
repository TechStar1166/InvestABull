"""Specialist agent runners.

Each ``run_*_specialist`` accepts:

* the ticker,
* the already-validated tool output(s) for that agent's domain,
* an optional ``LLMClient`` (for tests / custom providers),

and returns a fully-typed ``SpecialistAgentOutput[T]``.

Design
------
Specialists are deterministic *pipelines*, not CrewAI-style agents with their
own tool loops. We execute tool calls in Python (see ``app.tools``) and then
hand Gemini a **pre-validated** JSON payload. Its only job is interpretation,
not retrieval - that keeps numerical accuracy airtight and eliminates the
usual hallucination vectors.

Integration
-----------
* FastAPI: call these directly from ``app.services.pipeline`` (Phase 5).
* CrewAI: wrap each specialist as a single-step Task whose ``execute`` body
  delegates to the runner. The coordinator agent (Claude 3.5 Sonnet) remains
  a full CrewAI Agent.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Iterable, Type, TypeVar

from pydantic import BaseModel

from app.agents.llm import GeminiLLMClient, LLMClient
from app.agents.parsers import AgentOutputError, parse_agent_output
from app.agents.prompts import load_prompt
from app.rag.chroma_store import ChromaStore
from app.rag.retrieval import RetrievedChunk, query_filings
from app.schemas.common import AgentName
from app.schemas.macro import MacroIndicator
from app.schemas.news import NewsItem
from app.schemas.price import PriceMetrics
from app.schemas.specialist import (
    FilingsAgentOutput,
    MacroAgentOutput,
    NewsAgentOutput,
    PriceAgentOutput,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _default_llm() -> LLMClient:
    return GeminiLLMClient(model=DEFAULT_MODEL)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _render_user(ticker: str, tool_data: dict) -> str:
    payload = {
        "ticker": ticker.upper(),
        "as_of": _now().isoformat(),
        "tool_data": tool_data,
    }
    return (
        "Build the JSON output for the following ticker using ONLY the tool_data.\n\n"
        + json.dumps(payload, indent=2, default=str)
    )


def _run(
    llm: LLMClient,
    prompt_name: str,
    ticker: str,
    tool_data: dict,
    target_model: Type[T],
    *,
    max_retries: int = 1,
) -> T:
    """Execute a single-turn LLM call, parse, and self-correct once on failure."""
    system = load_prompt(prompt_name)
    user = _render_user(ticker, tool_data)
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        raw = llm.generate(system=system, user=user, json_mode=True)
        try:
            return parse_agent_output(raw, target_model)
        except AgentOutputError as e:
            last_err = e
            logger.warning(
                "specialist %s parse failed (attempt %d/%d): %s",
                prompt_name,
                attempt + 1,
                max_retries + 1,
                e,
            )
            user = (
                user
                + "\n\nYour previous response failed validation with error:\n"
                + str(e)
                + "\nReturn a corrected JSON object only."
            )
    raise AgentOutputError(
        f"specialist {prompt_name!r} failed {max_retries + 1} attempts: {last_err}"
    ) from last_err


def _stamp(out: T, *, agent_name: AgentName, llm: LLMClient, t0: float) -> T:
    """Overwrite envelope metadata the LLM should not control."""
    out.agent_name = agent_name  # type: ignore[attr-defined]
    out.model_used = getattr(llm, "model_name", None) or DEFAULT_MODEL  # type: ignore[attr-defined]
    out.latency_ms = int((time.monotonic() - t0) * 1000)  # type: ignore[attr-defined]
    return out


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------


def run_price_specialist(
    ticker: str,
    metrics: PriceMetrics,
    *,
    llm: LLMClient | None = None,
    max_retries: int = 1,
) -> PriceAgentOutput:
    """Interpret a ``PriceMetrics`` snapshot into a ``PriceAgentOutput``."""
    llm = llm or _default_llm()
    t0 = time.monotonic()
    tool_data = {"price_metrics": metrics.model_dump(mode="json")}
    out = _run(llm, "price", ticker, tool_data, PriceAgentOutput, max_retries=max_retries)
    return _stamp(out, agent_name=AgentName.PRICE, llm=llm, t0=t0)


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


def run_news_specialist(
    ticker: str,
    articles: list[NewsItem],
    *,
    window_days: int = 14,
    llm: LLMClient | None = None,
    max_retries: int = 1,
) -> NewsAgentOutput:
    """Classify sentiment / themes / risks across recent news articles."""
    llm = llm or _default_llm()
    t0 = time.monotonic()
    tool_data = {
        "window_days": int(window_days),
        "articles": [a.model_dump(mode="json") for a in articles],
    }
    out = _run(llm, "news", ticker, tool_data, NewsAgentOutput, max_retries=max_retries)
    return _stamp(out, agent_name=AgentName.NEWS, llm=llm, t0=t0)


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------


def run_macro_specialist(
    ticker: str,
    indicators: list[MacroIndicator],
    *,
    llm: LLMClient | None = None,
    max_retries: int = 1,
) -> MacroAgentOutput:
    """Interpret a bundle of FRED indicators into a company-agnostic macro view."""
    llm = llm or _default_llm()
    t0 = time.monotonic()
    tool_data = {"indicators": [i.model_dump(mode="json") for i in indicators]}
    out = _run(llm, "macro", ticker, tool_data, MacroAgentOutput, max_retries=max_retries)
    return _stamp(out, agent_name=AgentName.MACRO, llm=llm, t0=t0)


# ---------------------------------------------------------------------------
# Filings (RAG-backed)
# ---------------------------------------------------------------------------


DEFAULT_FILINGS_QUERIES: tuple[tuple[str, str], ...] = (
    ("risk_factors", "What are the most material risk factors?"),
    ("risk_factors", "What are the top regulatory and competitive risks?"),
    ("risk_factors", "What cybersecurity, supply-chain, or concentration risks are disclosed?"),
    ("business_overview", "What is the company's core business and key products?"),
    ("business_overview", "How does the company describe its competition?"),
    ("mdna", "What are management's key performance drivers and outlook?"),
    ("legal_proceedings", "What material legal proceedings are pending?"),
)


def retrieve_filing_context(
    store: ChromaStore,
    ticker: str,
    queries: Iterable[tuple[str, str]] = DEFAULT_FILINGS_QUERIES,
    *,
    k_per_query: int = 4,
) -> list[RetrievedChunk]:
    """Run the canonical query bundle and return chunks deduped by chunk_id.

    For duplicates, we keep the highest-scoring hit and return the list sorted
    descending by score (most relevant first).
    """
    seen: dict[str, RetrievedChunk] = {}
    for section, question in queries:
        hits = query_filings(
            store,
            question,
            ticker=ticker,
            sections=[section],
            k=k_per_query,
        )
        for h in hits:
            existing = seen.get(h.chunk_id)
            if existing is None or h.score > existing.score:
                seen[h.chunk_id] = h
    return sorted(seen.values(), key=lambda r: -r.score)


def run_filings_specialist(
    ticker: str,
    chunks: list[RetrievedChunk],
    *,
    llm: LLMClient | None = None,
    max_retries: int = 1,
) -> FilingsAgentOutput:
    """Synthesize retrieved 10-K chunks into a ``FilingsAgentOutput``."""
    llm = llm or _default_llm()
    t0 = time.monotonic()
    tool_data = {
        "retrieved_chunks": [
            {
                "chunk_id": c.chunk_id,
                "section": c.section,
                "score": round(float(c.score), 4),
                "text": c.text,
                "citation": c.citation.model_dump(mode="json"),
            }
            for c in chunks
        ],
    }
    out = _run(llm, "filings", ticker, tool_data, FilingsAgentOutput, max_retries=max_retries)
    return _stamp(out, agent_name=AgentName.FILINGS, llm=llm, t0=t0)
