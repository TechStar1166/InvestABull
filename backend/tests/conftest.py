"""Shared pytest fixtures.

Populates env vars the tool modules expect so ``get_settings()`` is
deterministic, then clears the Settings LRU cache so subsequent imports see
the test values.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the ``backend/`` directory (which contains the ``app`` package) is on
# sys.path when pytest is invoked from the repo root.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")
os.environ.setdefault("FRED_API_KEY", "test-fred-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("SEC_EDGAR_USER_AGENT", "InvestABull Test <test@example.com>")
os.environ.setdefault("HTTP_MAX_RETRIES", "1")  # keep test runs snappy

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()
