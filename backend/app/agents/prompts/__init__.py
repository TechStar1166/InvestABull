"""Specialist agent system prompts, loaded from sibling ``.md`` files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent

VALID_PROMPTS: frozenset[str] = frozenset({"price", "filings", "news", "macro"})


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Return the system-prompt text for a named specialist.

    Parameters
    ----------
    name:
        One of ``'price'``, ``'filings'``, ``'news'``, ``'macro'``.

    Raises
    ------
    ValueError
        If ``name`` is not a known prompt.
    FileNotFoundError
        If the expected ``.md`` file is missing on disk.
    """
    if name not in VALID_PROMPTS:
        raise ValueError(f"Unknown prompt {name!r}; expected one of {sorted(VALID_PROMPTS)}")
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


__all__ = ["VALID_PROMPTS", "load_prompt"]
