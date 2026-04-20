"""Shared backend schemas for research and streaming."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    """Single streaming trace event for SSE consumers."""

    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    stage: str
    agent: str
    status: str
    meta: dict[str, Any] | None = None
