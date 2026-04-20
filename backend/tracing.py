"""Utilities for formatting backend trace events for SSE."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from schemas import TraceEvent


def emit_trace(
    event: TraceEvent | None = None,
    *,
    stage: str | None = None,
    agent: str | None = None,
    status: str | None = None,
    meta: dict[str, Any] | None = None,
) -> str:
    """
    Build one trace event and format it as an SSE data frame.

    Example output:
        data: {"id":"...","status":"Starting",...}

    """
    if event is None:
        if stage is None or agent is None or status is None:
            raise ValueError("emit_trace requires an event or stage/agent/status fields.")
        event = TraceEvent(
            id=uuid4(),
            timestamp=datetime.utcnow(),
            stage=stage,
            agent=agent,
            status=status,
            meta=meta,
        )
    payload = json.dumps(event.model_dump(mode="json"))
    return f"data: {payload}\n\n"
