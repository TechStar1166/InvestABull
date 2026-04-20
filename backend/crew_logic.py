"""CrewAI orchestration for InvestABull equity research."""

from __future__ import annotations

import asyncio
import os
import re
from asyncio import Queue
from pathlib import Path
from typing import Any

from crewai import Agent, Crew, LLM, Process, Task
from dotenv import load_dotenv

from schemas import TraceEvent
from tools import TavilyNewsTool, YFinanceTool


class _LoggedYFinanceTool(YFinanceTool):
    """YFinanceTool with stdout timing (see terminal during /api/research)."""

    def _run(self, ticker: str) -> str:
        print(f"[InvestABull] YFinanceTool START ticker={ticker!r}", flush=True)
        try:
            return super()._run(ticker)
        finally:
            print("[InvestABull] YFinanceTool END", flush=True)


class _LoggedTavilyNewsTool(TavilyNewsTool):
    """TavilyNewsTool with stdout timing."""

    def _run(self, query: str) -> str:
        print(f"[InvestABull] TavilyNewsTool START query={query!r}", flush=True)
        try:
            return super()._run(query)
        finally:
            print("[InvestABull] TavilyNewsTool END", flush=True)


def _load_env() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")


def _sync_google_api_key() -> None:
    """
    LangChain Google GenAI expects GOOGLE_API_KEY.
    Many projects only set GEMINI_API_KEY — mirror it when GOOGLE_API_KEY is unset.
    """
    if os.environ.get("GOOGLE_API_KEY"):
        return
    gemini = os.environ.get("GEMINI_API_KEY")
    if gemini:
        os.environ["GOOGLE_API_KEY"] = gemini


def _require_env() -> None:
    _sync_google_api_key()
    missing: list[str] = []
    if not os.environ.get("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY (or GEMINI_API_KEY)")
    if not os.environ.get("TAVILY_API_KEY"):
        missing.append("TAVILY_API_KEY")
    if missing:
        raise RuntimeError(
            "Missing required environment variables in backend/.env: "
            + ", ".join(missing)
        )


def _normalize_ticker(ticker: str) -> str:
    cleaned = (ticker or "").strip().upper()
    if not cleaned or not re.fullmatch(r"[A-Z0-9.\-^]+", cleaned):
        raise ValueError("Invalid ticker: provide a non-empty US-style symbol (letters/digits).")
    return cleaned


def run_research(ticker: str) -> dict:
    """
    Run sequential CrewAI workflow: Gemini analyst (tools) -> coordinator memo.
    Primary coordinator is Claude; on Anthropic auth/billing issues, retry with Gemini.

    Returns:
        {"memo": str, "trace_logs": list[dict]}
    """
    _load_env()
    _require_env()
    symbol = _normalize_ticker(ticker)

    yfinance_tool = _LoggedYFinanceTool()
    tavily_tool = _LoggedTavilyNewsTool()

    # LiteLLM id for a currently available Gemini Flash model.
    gemini_llm = LLM(
        model="gemini/gemini-2.5-flash",
        api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.2,
    )
    claude_llm: LLM | None = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        claude_llm = LLM(
            model="anthropic/claude-3-5-sonnet-20240620",
            api_key=os.environ["ANTHROPIC_API_KEY"],
            temperature=0.2,
        )

    analyst = Agent(
        role="Financial Data Analyst",
        goal=(
            f"Collect verified quantitative data and recent news for {symbol} using the "
            "provided tools only—no invented figures or headlines."
        ),
        backstory=(
            "You are a sell-side research associate who trusts primary tool outputs over "
            "memory. You work quickly, cite tool-derived facts, and flag missing data explicitly."
        ),
        tools=[yfinance_tool, tavily_tool],
        llm=gemini_llm,
        verbose=True,
        allow_delegation=False,
    )

    def _build_crew(coordinator_llm: LLM) -> Crew:
        coordinator = Agent(
            role="Lead Portfolio Manager",
            goal=(
                "Transform raw analyst notes into a concise, decision-ready investment memo with a "
                "clear recommendation."
            ),
            backstory=(
                "You are a seasoned PM who synthesizes evidence, weighs catalysts against risks, "
                "and states a firm view (buy / hold / sell) with rationale grounded in the analyst output."
            ),
            tools=[],
            llm=coordinator_llm,
            verbose=True,
            allow_delegation=False,
        )

        data_task = Task(
            description=(
                "You are researching the company for US equity ticker {ticker}.\n"
                "1) Call `YFinanceTool` once with argument ticker=\"{ticker}\" and record all numeric "
                "facts and the business summary returned by the tool.\n"
                "2) Call `TavilyNewsTool` once with a single query string such as "
                "\"{ticker} stock latest news earnings\" and record headlines, URLs, and dates from "
                "the tool output.\n"
                "Do not fabricate prices, ratios, or news. If a tool reports an error, quote it and "
                "continue with what is available."
            ),
            expected_output=(
                "Structured bullet notes: (A) price & key ratios from YFinanceTool, "
                "(B) news items with source URLs from TavilyNewsTool, (C) explicit list of missing "
                "or failed data if any."
            ),
            agent=analyst,
        )

        synthesis_task = Task(
            description=(
                "Using only the prior task output as evidence, write a decisive investment memo for "
                "ticker {ticker}. Each section must be grounded in that context; if evidence is thin, "
                "say so explicitly rather than guessing."
            ),
            expected_output=(
                "A single Markdown document with exactly these top-level sections in order:\n"
                "### Executive Summary\n"
                "### Financial Overview\n"
                "### Key Catalysts & Risks\n"
                "### Investment Recommendation\n"
                "End the last section with an explicit stance: Buy, Hold, or Sell, plus 2–4 sentences "
                "of rationale tied to the analyst findings."
            ),
            agent=coordinator,
            context=[data_task],
        )

        return Crew(
            agents=[analyst, coordinator],
            tasks=[data_task, synthesis_task],
            process=Process.sequential,
            verbose=True,
        )

    def _is_anthropic_credential_or_billing_error(exc: Exception) -> bool:
        text = str(exc).lower()
        module = type(exc).__module__.lower()
        name = type(exc).__name__.lower()
        is_anthropic_exception = "anthropic" in module or "anthropic" in name
        return (
            (is_anthropic_exception or "anthropic" in text)
            and (
                "invalid authentication credentials" in text
                or "credit balance is too low" in text
                or "authentication_error" in text
                or "plans & billing" in text
                or "not_found_error" in text
                or "model: claude" in text
                or "error code: 401" in text
                or "error code: 400" in text
                or "error code: 404" in text
                or "notfounderror" in name
                or "authenticationerror" in name
                or "badrequesterror" in name
            )
        )

    # Preferred path: Claude coordinator when available.
    if claude_llm is not None:
        try:
            print("[InvestABull] Coordinator: Claude (primary)", flush=True)
            result = _build_crew(claude_llm).kickoff(inputs={"ticker": symbol})
        except Exception as exc:
            if not _is_anthropic_credential_or_billing_error(exc):
                raise
            print(
                "[InvestABull] Claude unavailable (auth/billing). Falling back to Gemini coordinator.",
                flush=True,
            )
            result = _build_crew(gemini_llm).kickoff(inputs={"ticker": symbol})
    else:
        print("[InvestABull] ANTHROPIC_API_KEY missing. Using Gemini coordinator.", flush=True)
        result = _build_crew(gemini_llm).kickoff(inputs={"ticker": symbol})

    return {
        "memo": result.raw,
        "trace_logs": [{"agent": "System", "status": "Live orchestration complete."}],
    }


async def run_crew_in_background(ticker: str, queue: Queue[TraceEvent | None]) -> None:
    """
    Run CrewAI kickoff in a worker thread while streaming TraceEvent objects into queue.
    The stream is closed by sending sentinel None.
    """
    _load_env()
    _require_env()
    symbol = _normalize_ticker(ticker)
    loop = asyncio.get_running_loop()

    def _enqueue_threadsafe(event: TraceEvent) -> None:
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    def _step_callback_factory(stage: str, agent_name: str):
        def _callback(step_output: Any) -> None:
            event = TraceEvent(
                stage=stage,
                agent=agent_name,
                status="Step completed",
                meta={
                    "ticker": symbol,
                    "step_preview": str(step_output)[:300] if step_output is not None else "",
                },
            )
            _enqueue_threadsafe(event)

        return _callback

    await queue.put(
        TraceEvent(
            stage="orchestration",
            agent="System",
            status="Starting Crew run",
            meta={"ticker": symbol},
        )
    )

    yfinance_tool = _LoggedYFinanceTool()
    tavily_tool = _LoggedTavilyNewsTool()

    gemini_llm = LLM(
        model="gemini/gemini-2.5-flash",
        api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.2,
    )
    claude_llm: LLM | None = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        claude_llm = LLM(
            model="anthropic/claude-3-5-sonnet-20240620",
            api_key=os.environ["ANTHROPIC_API_KEY"],
            temperature=0.2,
        )

    def _build_crew(coordinator_llm: LLM, coordinator_name: str) -> Crew:
        analyst = Agent(
            role="Financial Data Analyst",
            goal=(
                f"Collect verified quantitative data and recent news for {symbol} using the "
                "provided tools only—no invented figures or headlines."
            ),
            backstory=(
                "You are a sell-side research associate who trusts primary tool outputs over "
                "memory. You work quickly, cite tool-derived facts, and flag missing data explicitly."
            ),
            tools=[yfinance_tool, tavily_tool],
            llm=gemini_llm,
            verbose=True,
            allow_delegation=False,
            step_callback=_step_callback_factory("tool_execution", "Financial Data Analyst"),
        )

        coordinator = Agent(
            role="Lead Portfolio Manager",
            goal=(
                "Transform raw analyst notes into a concise, decision-ready investment memo with a "
                "clear recommendation."
            ),
            backstory=(
                "You are a seasoned PM who synthesizes evidence, weighs catalysts against risks, "
                "and states a firm view (buy / hold / sell) with rationale grounded in the analyst output."
            ),
            tools=[],
            llm=coordinator_llm,
            verbose=True,
            allow_delegation=False,
            step_callback=_step_callback_factory("synthesis", coordinator_name),
        )

        data_task = Task(
            description=(
                "You are researching the company for US equity ticker {ticker}.\n"
                "1) Call `YFinanceTool` once with argument ticker=\"{ticker}\" and record all numeric "
                "facts and the business summary returned by the tool.\n"
                "2) Call `TavilyNewsTool` once with a single query string such as "
                "\"{ticker} stock latest news earnings\" and record headlines, URLs, and dates from "
                "the tool output.\n"
                "Do not fabricate prices, ratios, or news. If a tool reports an error, quote it and "
                "continue with what is available."
            ),
            expected_output=(
                "Structured bullet notes: (A) price & key ratios from YFinanceTool, "
                "(B) news items with source URLs from TavilyNewsTool, (C) explicit list of missing "
                "or failed data if any."
            ),
            agent=analyst,
        )

        synthesis_task = Task(
            description=(
                "Using only the prior task output as evidence, write a decisive investment memo for "
                "ticker {ticker}. Each section must be grounded in that context; if evidence is thin, "
                "say so explicitly rather than guessing."
            ),
            expected_output=(
                "A single Markdown document with exactly these top-level sections in order:\n"
                "### Executive Summary\n"
                "### Financial Overview\n"
                "### Key Catalysts & Risks\n"
                "### Investment Recommendation\n"
            ),
            agent=coordinator,
            context=[data_task],
        )

        return Crew(
            agents=[analyst, coordinator],
            tasks=[data_task, synthesis_task],
            process=Process.sequential,
            verbose=True,
        )

    def _is_anthropic_fallback_candidate(exc: Exception) -> bool:
        text = str(exc).lower()
        module = type(exc).__module__.lower()
        name = type(exc).__name__.lower()
        return (("anthropic" in text) or ("anthropic" in module) or ("anthropic" in name)) and (
            "authentication_error" in text
            or "invalid authentication credentials" in text
            or "credit balance is too low" in text
            or "plans & billing" in text
            or "not_found_error" in text
            or "notfounderror" in name
            or "authenticationerror" in name
            or "badrequesterror" in name
        )

    try:
        await queue.put(
            TraceEvent(
                stage="orchestration",
                agent="System",
                status="Building crew",
                meta={"ticker": symbol},
            )
        )

        async def _kickoff_threaded(crew: Crew):
            return await asyncio.to_thread(crew.kickoff, inputs={"ticker": symbol})

        if claude_llm is not None:
            await queue.put(
                TraceEvent(
                    stage="orchestration",
                    agent="System",
                    status="Coordinator selected: Claude",
                    meta={"ticker": symbol},
                )
            )
            try:
                result = await _kickoff_threaded(_build_crew(claude_llm, "Lead Portfolio Manager"))
            except Exception as exc:
                if not _is_anthropic_fallback_candidate(exc):
                    raise
                await queue.put(
                    TraceEvent(
                        stage="orchestration",
                        agent="System",
                        status="Claude unavailable; falling back to Gemini coordinator",
                        meta={"error": str(exc)[:500]},
                    )
                )
                result = await _kickoff_threaded(_build_crew(gemini_llm, "Lead Portfolio Manager (Gemini)"))
        else:
            await queue.put(
                TraceEvent(
                    stage="orchestration",
                    agent="System",
                    status="Coordinator selected: Gemini (Anthropic key missing)",
                    meta={"ticker": symbol},
                )
            )
            result = await _kickoff_threaded(_build_crew(gemini_llm, "Lead Portfolio Manager (Gemini)"))

        await queue.put(
            TraceEvent(
                stage="synthesis",
                agent="System",
                status="Memo Ready",
                meta={"memo": result.raw},
            )
        )
    except Exception as exc:
        await queue.put(
            TraceEvent(
                stage="orchestration",
                agent="System",
                status="Error",
                meta={"error": str(exc)},
            )
        )
    finally:
        await queue.put(None)
