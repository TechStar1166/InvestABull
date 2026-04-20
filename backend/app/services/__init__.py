"""Service-layer functions exposed to FastAPI + CrewAI.

Public surface
--------------
* ``pipeline.run_specialist_pipeline(ticker) -> CoordinatorPayload`` -
  end-to-end runner that fans out to all four specialists concurrently and
  returns a coordinator-ready payload.
* ``coordinator_bridge.build_coordinator_prompt(payload)`` - assembles the
  (system, user) prompt pair for Claude 3.5 Sonnet from a payload.
"""

from app.services.coordinator_bridge import build_coordinator_prompt
from app.services.pipeline import CoordinatorPayload, run_specialist_pipeline

__all__ = [
    "CoordinatorPayload",
    "build_coordinator_prompt",
    "run_specialist_pipeline",
]
