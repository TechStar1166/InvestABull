"""FastAPI entry point for InvestABull backend + streaming bridge."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.services.pipeline import CoordinatorPayload, run_specialist_pipeline
from app.tools.base import InvalidInputError
from crew_logic import run_crew_in_background
from schemas import TraceEvent
from tracing import emit_trace

logger = logging.getLogger(__name__)

class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request id to every response (generated if the client omits it)."""

    header_name = "X-Request-ID"

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = request.headers.get(self.header_name) or str(uuid.uuid4())
        request.state.request_id = req_id
        t0 = time.monotonic()
        response = await call_next(request)
        response.headers[self.header_name] = req_id
        logger.info(
            "http %s %s -> %d in %d ms",
            request.method,
            request.url.path,
            response.status_code,
            int((time.monotonic() - t0) * 1000),
            extra={"request_id": req_id},
        )
        return response


class ResearchRequest(BaseModel):
    ticker: str = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Stock ticker symbol (case-insensitive).",
        examples=["AAPL", "MSFT", "NVDA"],
    )


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "investabull-backend"

def create_app() -> FastAPI:
    app = FastAPI(
        title="InvestABull - Multi-Agent Equity Research",
        version="0.1.0",
        description=(
            "Runs four specialist agents (Price / Filings / News / Macro) "
            "against a ticker and returns a coordinator-ready payload."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.post(
        "/research",
        response_model=CoordinatorPayload,
        tags=["research"],
        summary="Run the full specialist pipeline for a ticker.",
    )
    async def research(req: ResearchRequest) -> CoordinatorPayload:
        try:
            return await asyncio.to_thread(run_specialist_pipeline, req.ticker)
        except InvalidInputError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("unexpected pipeline failure")
            raise HTTPException(status_code=500, detail=f"pipeline error: {e}") from e

    @app.post(
        "/api/research",
        response_model=CoordinatorPayload,
        tags=["research"],
        summary="Backward-compatible alias of /research.",
    )
    async def api_research(req: ResearchRequest) -> CoordinatorPayload:
        try:
            return await asyncio.to_thread(run_specialist_pipeline, req.ticker)
        except InvalidInputError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("unexpected pipeline failure")
            raise HTTPException(status_code=500, detail=f"pipeline error: {e}") from e

    @app.post(
        "/api/research/stream",
        tags=["research"],
        summary="Stream specialist pipeline progress and final memo payload over SSE.",
    )
    async def api_research_stream(req: ResearchRequest) -> StreamingResponse:
        queue: asyncio.Queue[TraceEvent | None] = asyncio.Queue()
        asyncio.create_task(run_crew_in_background(req.ticker, queue))

        async def stream_events():
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield emit_trace(event=item)

        return StreamingResponse(stream_events(), media_type="text/event-stream")

    return app


app = create_app()
