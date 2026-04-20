"""Orchestrate all four specialist agents behind a single entry point.

``run_specialist_pipeline(ticker)`` is the service-level seam that FastAPI and
CrewAI (`crew_logic.py`) both call. It:

1. Normalizes the ticker once at the boundary.
2. Fans out to the four domain runners concurrently via a ``ThreadPoolExecutor``
   (each runner is sync and IO-bound - HTTP to yfinance/Tavily/FRED/SEC plus
   the Gemini call - so threads parallelize cleanly without dragging asyncio
   through every tool).
3. Catches per-domain exceptions and substitutes a ``status=failed`` envelope
   so the coordinator *always* receives all four envelopes in the same shape.
   A single bad upstream never brings the whole memo down.
4. Returns a typed ``CoordinatorPayload`` containing every envelope plus a
   run-level ``correlation_id``, ``started_at`` / ``finished_at``, and the
   end-to-end latency.

Downstream consumers (Claude coordinator, FastAPI JSON response, CrewAI
Task inputs) only ever see ``CoordinatorPayload`` - the concurrency,
error-mapping, and RAG ingestion details stay internal to this module.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.agents.llm import LLMClient
from app.agents.parsers import AgentOutputError
from app.agents.specialists import (
    retrieve_filing_context,
    run_filings_specialist,
    run_macro_specialist,
    run_news_specialist,
    run_price_specialist,
)
from app.config import get_settings
from app.rag.chroma_store import ChromaStore
from app.rag.ingestion import ingest_latest_10k
from app.schemas.common import AgentName, AgentStatus
from app.schemas.filings import FilingsFindings
from app.schemas.macro import MacroDigest
from app.schemas.news import NewsDigest
from app.schemas.price import PriceMetrics
from app.schemas.specialist import (
    FilingsAgentOutput,
    MacroAgentOutput,
    NewsAgentOutput,
    PriceAgentOutput,
)
from app.tools.base import NoDataError, ToolError, validate_ticker
from app.tools.fred_tool import fetch_macro_bundle
from app.tools.tavily_tool import search_ticker_news
from app.tools.yfinance_tool import fetch_price_metrics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Coordinator-ready payload
# ---------------------------------------------------------------------------


class CoordinatorPayload(BaseModel):
    """Everything the coordinator (Claude 3.5 Sonnet) needs to write the memo.

    The four specialist envelopes are always present. Failed specialists
    surface as ``status=failed`` envelopes with a populated ``errors`` list
    and zero confidence - the coordinator can reason about partial coverage
    without ever dealing with ``None`` branches.
    """

    correlation_id: str = Field(
        ...,
        description="UUID for this research run; use to correlate logs / traces.",
    )
    ticker: str
    started_at: datetime
    finished_at: datetime
    latency_ms: int = Field(..., ge=0)

    price: PriceAgentOutput
    filings: FilingsAgentOutput
    news: NewsAgentOutput
    macro: MacroAgentOutput

    pipeline_errors: list[str] = Field(
        default_factory=list,
        description="Orchestration-level errors (not tied to a single specialist).",
    )


# ---------------------------------------------------------------------------
# Default factories (overridable for tests)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _default_store() -> ChromaStore:
    """Module-level ChromaDB singleton.

    Instantiating ``PersistentClient`` is cheap but opens a SQLite handle;
    reusing one instance across requests avoids leaking file descriptors.
    """
    settings = get_settings()
    return ChromaStore(persist_dir=settings.chroma_persist_dir)


def _default_llm_factory() -> LLMClient:
    from app.agents.llm import GeminiLLMClient

    return GeminiLLMClient()


# ---------------------------------------------------------------------------
# Failure envelope helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _failed_price(ticker: str, error: str, *, status: AgentStatus = AgentStatus.FAILED) -> PriceAgentOutput:
    now = _now()
    return PriceAgentOutput(
        agent_name=AgentName.PRICE,
        ticker=ticker,
        as_of_date=now,
        status=status,
        summary=f"Price specialist did not produce findings: {error}",
        findings=PriceMetrics(ticker=ticker, as_of=now),
        confidence=0.0,
        errors=[error],
    )


def _failed_news(ticker: str, error: str, *, status: AgentStatus = AgentStatus.FAILED) -> NewsAgentOutput:
    return NewsAgentOutput(
        agent_name=AgentName.NEWS,
        ticker=ticker,
        as_of_date=_now(),
        status=status,
        summary=f"News specialist did not produce findings: {error}",
        findings=NewsDigest(),
        confidence=0.0,
        errors=[error],
    )


def _failed_macro(ticker: str, error: str, *, status: AgentStatus = AgentStatus.FAILED) -> MacroAgentOutput:
    return MacroAgentOutput(
        agent_name=AgentName.MACRO,
        ticker=ticker,
        as_of_date=_now(),
        status=status,
        summary=f"Macro specialist did not produce findings: {error}",
        findings=MacroDigest(),
        confidence=0.0,
        errors=[error],
    )


def _failed_filings(ticker: str, error: str, *, status: AgentStatus = AgentStatus.FAILED) -> FilingsAgentOutput:
    return FilingsAgentOutput(
        agent_name=AgentName.FILINGS,
        ticker=ticker,
        as_of_date=_now(),
        status=status,
        summary=f"Filings specialist did not produce findings: {error}",
        findings=FilingsFindings(),
        confidence=0.0,
        errors=[error],
    )


# ---------------------------------------------------------------------------
# Per-domain runners
# ---------------------------------------------------------------------------


def _run_price_domain(ticker: str, llm: LLMClient) -> PriceAgentOutput:
    try:
        metrics = fetch_price_metrics(ticker)
    except NoDataError as e:
        logger.warning("price tool NoDataError for %s: %s", ticker, e)
        return _failed_price(ticker, f"no price data: {e}", status=AgentStatus.NO_DATA)
    except ToolError as e:
        logger.warning("price tool failed for %s: %s", ticker, e)
        return _failed_price(ticker, f"price tool failed: {e}")
    try:
        return run_price_specialist(ticker, metrics, llm=llm)
    except (AgentOutputError, Exception) as e:  # noqa: BLE001 - intentional catch-all
        logger.exception("price specialist failed for %s", ticker)
        return _failed_price(ticker, f"price specialist failed: {e}")


def _run_news_domain(ticker: str, llm: LLMClient) -> NewsAgentOutput:
    try:
        articles = search_ticker_news(ticker)
    except NoDataError:
        # No articles is a legitimate outcome - still run the specialist so the
        # coordinator receives a valid digest ("nothing material this window").
        articles = []
    except ToolError as e:
        logger.warning("news tool failed for %s: %s", ticker, e)
        return _failed_news(ticker, f"news tool failed: {e}")
    try:
        return run_news_specialist(ticker, articles, llm=llm)
    except (AgentOutputError, Exception) as e:  # noqa: BLE001
        logger.exception("news specialist failed for %s", ticker)
        return _failed_news(ticker, f"news specialist failed: {e}")


def _run_macro_domain(ticker: str, llm: LLMClient) -> MacroAgentOutput:
    try:
        indicators = fetch_macro_bundle()
    except ToolError as e:
        logger.warning("macro tool failed: %s", e)
        return _failed_macro(ticker, f"macro tool failed: {e}")
    if not indicators:
        return _failed_macro(ticker, "no FRED indicators available", status=AgentStatus.NO_DATA)
    try:
        return run_macro_specialist(ticker, indicators, llm=llm)
    except (AgentOutputError, Exception) as e:  # noqa: BLE001
        logger.exception("macro specialist failed for %s", ticker)
        return _failed_macro(ticker, f"macro specialist failed: {e}")


def _run_filings_domain(ticker: str, llm: LLMClient, store: ChromaStore) -> FilingsAgentOutput:
    try:
        ingest_latest_10k(ticker, store)
    except NoDataError as e:
        return _failed_filings(
            ticker, f"no 10-K available: {e}", status=AgentStatus.NO_DATA
        )
    except ToolError as e:
        logger.warning("filings ingestion failed for %s: %s", ticker, e)
        return _failed_filings(ticker, f"filings ingestion failed: {e}")

    chunks = retrieve_filing_context(store, ticker)
    if not chunks:
        return _failed_filings(
            ticker,
            "filing ingested but no relevant chunks retrieved",
            status=AgentStatus.NO_DATA,
        )
    try:
        return run_filings_specialist(ticker, chunks, llm=llm)
    except (AgentOutputError, Exception) as e:  # noqa: BLE001
        logger.exception("filings specialist failed for %s", ticker)
        return _failed_filings(ticker, f"filings specialist failed: {e}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_specialist_pipeline(
    ticker: str,
    *,
    llm: LLMClient | None = None,
    store: ChromaStore | None = None,
    llm_factory: Callable[[], LLMClient] | None = None,
    max_workers: int = 4,
    on_specialist_result: Callable[[str, str, Any], None] | None = None,
) -> CoordinatorPayload:
    """Run all four specialists concurrently and return a coordinator-ready payload.

    Parameters
    ----------
    ticker
        Stock ticker. Normalized via ``validate_ticker`` before dispatch.
    llm
        Optional pre-built ``LLMClient`` shared across all four specialists.
        For production, pass ``None`` and let each specialist build its own
        stateless ``GeminiLLMClient`` via ``llm_factory``.
    store
        Optional pre-built ``ChromaStore``. Defaults to the module singleton.
    llm_factory
        Called once if ``llm`` is ``None`` - primarily a test seam.
    max_workers
        Thread pool size; 4 is enough since we have 4 independent fanouts.
    on_specialist_result
        Optional callback invoked after each specialist future completes, in
        wait order: Price, News, Macro, Filings. Arguments are
        ``(agent_label, status_value, envelope)`` for SSE / tracing.

    Notes
    -----
    A single ``LLMClient`` instance is safe to share across threads because
    ``GeminiLLMClient`` only wraps the ``google.generativeai`` SDK, which is
    itself thread-safe for read-only ``generate_content`` calls.
    """
    correlation_id = str(uuid.uuid4())
    started_at = _now()
    t0 = time.monotonic()

    symbol = validate_ticker(ticker)
    llm = llm or (llm_factory or _default_llm_factory)()
    store = store or _default_store()

    logger.info(
        "pipeline start",
        extra={"correlation_id": correlation_id, "ticker": symbol},
    )

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="specialist") as pool:
        f_price = pool.submit(_run_price_domain, symbol, llm)
        f_news = pool.submit(_run_news_domain, symbol, llm)
        f_macro = pool.submit(_run_macro_domain, symbol, llm)
        f_filings = pool.submit(_run_filings_domain, symbol, llm, store)

        price_out = f_price.result()
        if on_specialist_result:
            on_specialist_result("Price", price_out.status.value, price_out)

        news_out = f_news.result()
        if on_specialist_result:
            on_specialist_result("News", news_out.status.value, news_out)

        macro_out = f_macro.result()
        if on_specialist_result:
            on_specialist_result("Macro", macro_out.status.value, macro_out)

        filings_out = f_filings.result()
        if on_specialist_result:
            on_specialist_result("Filings", filings_out.status.value, filings_out)

    finished_at = _now()
    latency_ms = int((time.monotonic() - t0) * 1000)

    payload = CoordinatorPayload(
        correlation_id=correlation_id,
        ticker=symbol,
        started_at=started_at,
        finished_at=finished_at,
        latency_ms=latency_ms,
        price=price_out,
        filings=filings_out,
        news=news_out,
        macro=macro_out,
    )

    logger.info(
        "pipeline done",
        extra={
            "correlation_id": correlation_id,
            "ticker": symbol,
            "latency_ms": latency_ms,
            "statuses": {
                "price": price_out.status.value,
                "filings": filings_out.status.value,
                "news": news_out.status.value,
                "macro": macro_out.status.value,
            },
        },
    )
    return payload
