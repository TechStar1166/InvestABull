"""Assemble a Claude-ready prompt from a ``CoordinatorPayload``.

Scope
-----
This module sits on the boundary between the Data/API domain and the AI
Orchestration Lead's coordinator. It is intentionally narrow: build the
(system, user) prompt pair and nothing else. Actually calling Claude 3.5
Sonnet, validating a ``FinalMemo`` schema, and wiring it into CrewAI all
belong to the coordinator owner.

Why it lives here
-----------------
Deciding *what JSON the coordinator sees* is a data-contract concern. Keeping
the prompt assembly next to ``CoordinatorPayload`` guarantees both sides stay
in sync: if the envelope schema changes, the prompt rebuilds automatically
from ``model_dump_json``.
"""

from __future__ import annotations

from typing import Literal

from app.schemas.specialist import SpecialistAgentOutput
from app.services.pipeline import CoordinatorPayload

CoordinatorRole = Literal["system", "user"]

SYSTEM_PROMPT = """\
You are the Coordinator Agent in an institutional-style multi-agent equity research system.

Four specialist agents have independently analyzed a single ticker:
  - PRICE    - quantitative snapshot from yfinance
  - FILINGS  - 10-K synthesis via SEC EDGAR + RAG
  - NEWS     - recent-news sentiment via Tavily
  - MACRO    - macroeconomic regime via FRED

Each specialist returns a SpecialistAgentOutput envelope with the SAME shape:
  agent_name, ticker, as_of_date, status, summary, bullet_points, findings,
  risks, confidence, citations, raw_data_notes, assumptions, errors.

Your job is to synthesize their outputs into a single, auditable investment
memo. You MUST:

1. Use ONLY facts present in the specialist envelopes. Never invent numbers,
   dates, or citations. If something is missing, say so.
2. Reconcile disagreements explicitly (e.g. bullish price action vs. negative
   news sentiment) rather than averaging them away.
3. Down-weight any specialist whose status is "failed", "no_data", or
   "partial", or whose confidence is low. State your weighting in the memo.
4. Preserve every citation that backs a claim you repeat. Cite by the
   specialist's source_name + identifier verbatim.
5. Separate factual findings, interpretation, and risks in your output.
"""


def _envelope_block(label: str, env: SpecialistAgentOutput) -> str:
    """Render one specialist envelope as a fenced JSON block."""
    body = env.model_dump_json(indent=2)
    return f"### {label}\n```json\n{body}\n```"


def build_coordinator_prompt(payload: CoordinatorPayload) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for the coordinator LLM.

    The user prompt serializes every specialist envelope as a fenced JSON
    block so Claude can reason over the full structure without us having to
    lossy-flatten it into prose.
    """
    header = (
        f"Ticker: {payload.ticker}\n"
        f"Run: {payload.correlation_id}\n"
        f"Started: {payload.started_at.isoformat()}\n"
        f"Finished: {payload.finished_at.isoformat()}\n"
        f"Pipeline latency: {payload.latency_ms} ms\n"
    )
    envelopes = "\n\n".join(
        [
            _envelope_block("PRICE", payload.price),
            _envelope_block("FILINGS", payload.filings),
            _envelope_block("NEWS", payload.news),
            _envelope_block("MACRO", payload.macro),
        ]
    )

    instructions = (
        "Produce the final investment memo as JSON only. The memo must contain:\n"
        "- thesis: 2-4 sentence directional view (bullish / bearish / mixed).\n"
        "- key_findings: 5-10 bullet points, each tagged with the source specialist.\n"
        "- cross_agent_reconciliation: where do specialists disagree and how do you weight them?\n"
        "- risks: top 5 risks with citations copied verbatim from the specialists.\n"
        "- confidence: overall memo confidence in [0, 1], justified by specialist statuses / confidences.\n"
        "- data_gaps: anything missing that a human analyst should collect next.\n"
    )

    user = (
        header
        + "\nSpecialist envelopes follow. Treat them as the ground truth.\n\n"
        + envelopes
        + "\n\n"
        + instructions
    )
    return SYSTEM_PROMPT, user


MARKDOWN_SYSTEM_PROMPT = """\
You are the Coordinator Agent (Claude 3.5 Sonnet) in an institutional equity research system.

Four Gemini-powered specialists have produced structured envelopes for one ticker:
PRICE, FILINGS, NEWS, MACRO. You receive their JSON exactly as emitted by the pipeline.

Write a single investment memo in Markdown only. Ground every claim in the envelopes; do
not invent figures, dates, or URLs. If a specialist status is failed or no_data, say so.

Use EXACTLY these top-level sections in order, each starting with ###:
### Executive Summary
### Financial Overview
### Key Catalysts & Risks
### Investment Recommendation

End Investment Recommendation with an explicit stance: Buy, Hold, or Sell, with rationale.
"""


def build_coordinator_markdown_prompt(payload: CoordinatorPayload) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for a Markdown investment memo."""
    header = (
        f"Ticker: {payload.ticker}\n"
        f"Run: {payload.correlation_id}\n"
        f"Started: {payload.started_at.isoformat()}\n"
        f"Finished: {payload.finished_at.isoformat()}\n"
        f"Pipeline latency: {payload.latency_ms} ms\n"
    )
    envelopes = "\n\n".join(
        [
            _envelope_block("PRICE", payload.price),
            _envelope_block("FILINGS", payload.filings),
            _envelope_block("NEWS", payload.news),
            _envelope_block("MACRO", payload.macro),
        ]
    )
    user = (
        header
        + "\nBelow are the four specialist envelopes (ground truth).\n\n"
        + envelopes
    )
    return MARKDOWN_SYSTEM_PROMPT, user
