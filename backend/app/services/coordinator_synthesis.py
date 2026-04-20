"""Claude coordinator: Markdown memo from ``CoordinatorPayload``."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.services.coordinator_bridge import build_coordinator_markdown_prompt
from app.services.pipeline import CoordinatorPayload

logger = logging.getLogger(__name__)


def synthesize_coordinator_markdown(
    payload: CoordinatorPayload,
) -> tuple[str, bool, str | None]:
    """Call Anthropic Claude; return ``(memo, used_claude, model_id_used)``.

    If ``ANTHROPIC_API_KEY`` is missing or the call fails, returns a fallback memo
    and ``used_claude=False``, ``model_id_used=None``.
    """
    settings = get_settings()
    key = settings.anthropic_api_key
    if not key:
        logger.warning("ANTHROPIC_API_KEY not set; skipping Claude coordinator")
        return _fallback_memo(payload, reason="ANTHROPIC_API_KEY not configured"), False, None

    system, user = build_coordinator_markdown_prompt(payload)
    preferred = (settings.anthropic_model or "").strip()
    # Many API keys no longer resolve legacy 3.5 snapshot IDs (404). Sonnet 4.6 is the
    # current production Sonnet on the Messages API for most accounts.
    candidates = [
        preferred,
        "claude-sonnet-4-6",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-20240620",
        "claude-sonnet-4-20250514",
        "claude-3-5-haiku-20241022",
    ]
    seen: set[str] = set()

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        last_err: Exception | None = None
        for model in candidates:
            if not model or model in seen:
                continue
            seen.add(model)
            try:
                msg = client.messages.create(
                    model=model,
                    max_tokens=8192,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                block = msg.content[0]
                text = getattr(block, "text", None) or str(block)
                text = (text or "").strip()
                if not text:
                    last_err = RuntimeError("Claude returned empty content")
                    continue
                logger.info("Claude memo ok model=%s", model)
                return text, True, model
            except anthropic.NotFoundError as e:
                last_err = e
                logger.warning("Claude model not available: %s (%s)", model, e)
                continue
        if last_err:
            return _fallback_memo(payload, reason=str(last_err)), False, None
        return _fallback_memo(payload, reason="no Claude model candidates"), False, None
    except Exception as e:  # noqa: BLE001
        logger.exception("Claude coordinator failed: %s", e)
        return _fallback_memo(payload, reason=str(e)), False, None


def _fallback_memo(payload: CoordinatorPayload, *, reason: str) -> str:
    return "\n".join(
        [
            f"### Executive Summary ({payload.ticker})",
            f"Claude coordinator unavailable ({reason}). Showing pipeline summary only.",
            "",
            "### Financial Overview",
            f"- Price: `{payload.price.status.value}` — {payload.price.summary[:500]}",
            "",
            "### Key Catalysts & Risks",
            f"- Filings: `{payload.filings.status.value}`",
            f"- News: `{payload.news.status.value}`",
            f"- Macro: `{payload.macro.status.value}`",
            "",
            "### Investment Recommendation",
            "Hold pending coordinator: configure ANTHROPIC_API_KEY and retry.",
        ]
    )
