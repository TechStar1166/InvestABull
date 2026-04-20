"""InvestABull FastAPI entrypoint."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from crew_logic import run_crew_in_background, run_research
from schemas import TraceEvent
from tracing import emit_trace

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parent / ".env")

app = FastAPI(title="InvestABull Multi-Agent API")


class ResearchRequest(BaseModel):
    ticker: str = Field(..., min_length=1, description="US equity ticker, e.g. AAPL")


@app.post("/api/research")
async def api_research(body: ResearchRequest) -> dict:
    """
    Crew synthesis can take many minutes. Run blocking work off the event loop so
    OpenAPI / health checks stay responsive; clients should use a long read timeout (e.g. 300s).
    """
    try:
        return await asyncio.to_thread(run_research, body.ticker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("run_research failed")
        text = str(exc).lower()
        if "429" in str(exc) or "resource_exhausted" in text or "credits are depleted" in text:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Gemini returned HTTP 429 (quota or billing). "
                    "Open https://aistudio.google.com/ and add credits or switch API key / project."
                ),
            ) from exc
        raise HTTPException(
            status_code=500,
            detail="Research pipeline failed.",
        ) from exc


@app.post("/api/research/stream")
async def api_research_stream(body: ResearchRequest) -> StreamingResponse:
    queue: asyncio.Queue[TraceEvent | None] = asyncio.Queue()
    asyncio.create_task(run_crew_in_background(body.ticker, queue))

    async def stream_events():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield emit_trace(event=item)

    return StreamingResponse(stream_events(), media_type="text/event-stream")
