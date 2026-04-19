"""CrewAI topology sketch (handoff hook for the AI Orchestration Lead).

Why this file is a sketch, not an implementation
------------------------------------------------
The specialist agents in this repo are deterministic *pipelines*
(`app.agents.specialists.run_*_specialist`) rather than free-loop CrewAI
Agents. That is a deliberate design choice: tool calls happen in Python so
numerical outputs are never re-typed by an LLM, and the Gemini step only
interprets pre-validated JSON.

CrewAI's strength - a coordinator reasoning over agent outputs - plugs in on
the *synthesis* side. The intended topology is:

    [Price Task]   -> run_price_specialist(ticker, metrics)
    [Filings Task] -> run_filings_specialist(ticker, chunks)   \
    [News Task]    -> run_news_specialist(ticker, articles)     >  Coordinator Agent
    [Macro Task]   -> run_macro_specialist(ticker, indicators) /   (Claude 3.5 Sonnet)

This file exposes ``build_crew(ticker)`` as an editable seam so AG can wire
the actual Agent/Task/Crew objects without touching the data layer.

Status: CrewAI is not imported at runtime here to avoid a hard dependency on
agent mode until the coordinator is wired. Replace the ``NotImplementedError``
stubs with real Agent/Task/Crew constructors when ready.
"""

from __future__ import annotations

from typing import Any

from app.services.coordinator_bridge import build_coordinator_prompt
from app.services.pipeline import CoordinatorPayload, run_specialist_pipeline


def build_crew(ticker: str) -> Any:
    """Construct the CrewAI Crew for a single research run.

    AG - drop your CrewAI wiring here. Suggested structure::

        from crewai import Agent, Task, Crew, Process, LLM

        coord_llm = LLM(model="anthropic/claude-3-5-sonnet-20240620")

        price_task   = Task(description="Run price specialist",
                            agent=price_agent,
                            expected_output="PriceAgentOutput JSON",
                            async_execution=True)
        # ... same for filings / news / macro ...

        coordinator = Agent(
            role="Investment Memo Coordinator",
            goal="Synthesize four specialist envelopes into a final memo.",
            backstory="Senior equity analyst. Skeptical, precise, citation-first.",
            llm=coord_llm,
            allow_delegation=False,
        )
        synthesis = Task(
            description="Read all four envelopes and emit a FinalMemo JSON.",
            agent=coordinator,
            context=[price_task, filings_task, news_task, macro_task],
            expected_output="FinalMemo JSON",
        )

        return Crew(
            agents=[price_agent, filings_agent, news_agent, macro_agent, coordinator],
            tasks=[price_task, filings_task, news_task, macro_task, synthesis],
            process=Process.sequential,
        )

    Each specialist Agent's ``execute`` body should call the matching
    ``run_*_specialist`` helper from ``app.agents.specialists`` so the
    deterministic tool + prompt pipeline stays authoritative.
    """
    raise NotImplementedError(
        "CrewAI wiring is owned by the AI Orchestration Lead. "
        "Populate this with Agent/Task/Crew constructors per the docstring."
    )


# ---------------------------------------------------------------------------
# Shortcut path: skip CrewAI and go straight through the service layer.
# Handy while the coordinator is being built.
# ---------------------------------------------------------------------------


def run_research_memo(ticker: str) -> tuple[CoordinatorPayload, tuple[str, str]]:
    """Run the full specialist pipeline + build the coordinator prompt.

    Returns
    -------
    payload : CoordinatorPayload
        The four specialist envelopes, wrapped with run metadata.
    prompt : tuple[str, str]
        ``(system_prompt, user_prompt)`` ready to hand to Claude 3.5 Sonnet.
        The actual LLM call is intentionally not made here - that is the
        coordinator owner's job.
    """
    payload = run_specialist_pipeline(ticker)
    prompt = build_coordinator_prompt(payload)
    return payload, prompt
