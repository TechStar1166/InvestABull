"""Resilient JSON extraction for specialist agent outputs.

The specialist prompts instruct Gemini to return a single JSON object with no
surrounding text. In practice we still see occasional markdown fences or
explanatory preambles, so this module recovers gracefully:

1. Strip leading/trailing markdown fences.
2. Try to validate the whole body against the target Pydantic model.
3. Fall back to the largest balanced ``{...}`` block found anywhere in the
   response, then try again.
4. Raise a typed ``AgentOutputError`` if nothing parses.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AgentOutputError(Exception):
    """Raised when a specialist's LLM output can't be parsed into the target schema."""


_OPEN_FENCE = re.compile(r"^```(?:json)?\s*\n?", flags=re.IGNORECASE)
_CLOSE_FENCE = re.compile(r"\n?```\s*$")


def _strip_fences(text: str) -> str:
    """Remove a single outer ```json ... ``` wrapper, if present."""
    text = text.strip()
    text = _OPEN_FENCE.sub("", text, count=1)
    text = _CLOSE_FENCE.sub("", text, count=1)
    return text.strip()


def _largest_json_block(text: str) -> str | None:
    """Return the widest balanced ``{...}`` block in ``text``, or ``None``."""
    best: tuple[int, int] | None = None
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    length = i - start + 1
                    if best is None or length > (best[1] - best[0] + 1):
                        best = (start, i)
    if best is None:
        return None
    return text[best[0] : best[1] + 1]


def parse_agent_output(raw: str, model_cls: Type[T]) -> T:
    """Parse ``raw`` LLM output into ``model_cls``.

    Raises
    ------
    AgentOutputError
        If no valid JSON matching the schema can be recovered.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise AgentOutputError("LLM returned empty output")

    candidates: list[str] = []
    stripped = _strip_fences(raw)
    candidates.append(stripped)
    block = _largest_json_block(stripped)
    if block and block != stripped:
        candidates.append(block)

    last_err: Exception | None = None
    for cand in candidates:
        try:
            return model_cls.model_validate_json(cand)
        except (ValidationError, json.JSONDecodeError) as e:
            last_err = e
            logger.debug("parse attempt failed: %s", e)

    raise AgentOutputError(
        f"Could not parse LLM output as {model_cls.__name__}: {last_err}"
    ) from last_err
