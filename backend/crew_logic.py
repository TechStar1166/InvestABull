"""Bridge async SSE streaming with the modular specialist pipeline + Claude coordinator."""

from __future__ import annotations

import asyncio
from asyncio import Queue
from typing import Any

from app.services.coordinator_synthesis import synthesize_coordinator_markdown
from app.services.pipeline import CoordinatorPayload, run_specialist_pipeline
from app.tools.base import InvalidInputError
from schemas import TraceEvent


def run_research(ticker: str) -> dict:
    """Compatibility wrapper for non-streaming endpoint callers."""
    payload = run_specialist_pipeline(ticker)
    memo, used_claude, model_used = synthesize_coordinator_markdown(payload)
    return {
        "memo": memo,
        "trace_logs": [
            {
                "agent": "System",
                "status": "Pipeline + coordinator complete.",
                "meta": {
                    "correlation_id": payload.correlation_id,
                    "claude": used_claude,
                    "anthropic_model": model_used,
                },
            }
        ],
        "payload": payload.model_dump(mode="json"),
    }


async def run_crew_in_background(ticker: str, queue: Queue[TraceEvent | None]) -> None:
    """
    Run specialists (Gemini) then Claude coordinator; stream TraceEvents.

    Thread safety: sync pipeline thread uses run_coroutine_threadsafe to push events.
    """
    loop = asyncio.get_running_loop()
    await queue.put(
        TraceEvent(
            stage="orchestration",
            agent="System",
            status="Starting specialist pipeline",
            meta={"ticker": ticker},
        )
    )

    def emit_from_thread(event: TraceEvent) -> None:
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    def run_sync_pipeline() -> tuple[CoordinatorPayload, str, bool]:
        emit_from_thread(
            TraceEvent(
                stage="orchestration",
                agent="System",
                status="Fanning out Price / News / Macro / Filings (Gemini)",
                meta={"ticker": ticker},
            )
        )

        def on_specialist_result(agent: str, status: str, envelope: Any) -> None:
            emit_from_thread(
                TraceEvent(
                    stage="tool_execution",
                    agent=f"{agent} Specialist",
                    status=f"Complete ({status})",
                    meta={
                        "ticker": ticker,
                        "specialist": agent,
                        "envelope_status": status,
                    },
                )
            )

        payload = run_specialist_pipeline(ticker, on_specialist_result=on_specialist_result)

        emit_from_thread(
            TraceEvent(
                stage="synthesis",
                agent="System",
                status="CoordinatorPayload ready for Claude",
                meta={
                    "ticker": payload.ticker,
                    "correlation_id": payload.correlation_id,
                    "latency_ms": payload.latency_ms,
                },
            )
        )

        emit_from_thread(
            TraceEvent(
                stage="synthesis",
                agent="Coordinator (Claude)",
                status="Synthesizing Markdown memo",
                meta={"ticker": ticker},
            )
        )
        memo, used_claude, model_used = synthesize_coordinator_markdown(payload)
        return payload, memo, used_claude, model_used

    try:
        payload, memo, used_claude, model_used = await asyncio.to_thread(run_sync_pipeline)
        await queue.put(
            TraceEvent(
                stage="synthesis",
                agent="System",
                status="Memo Ready",
                meta={
                    "memo": memo,
                    "coordinator": "claude" if used_claude else "fallback",
                    "anthropic_model": model_used,
                    "payload": payload.model_dump(mode="json"),
                },
            )
        )
    except InvalidInputError as exc:
        await queue.put(
            TraceEvent(
                stage="orchestration",
                agent="System",
                status="Error",
                meta={"error": str(exc), "error_type": "invalid_input"},
            )
        )
    except Exception as exc:  # noqa: BLE001
        await queue.put(
            TraceEvent(
                stage="orchestration",
                agent="System",
                status="Error",
                meta={"error": str(exc), "error_type": "pipeline_failure"},
            )
        )
    finally:
        await queue.put(None)
