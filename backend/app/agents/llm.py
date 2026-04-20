"""LLM client abstraction used by specialist agents.

We expose a minimal ``LLMClient`` Protocol so specialists accept either the
production ``GeminiLLMClient`` (Gemini 2.5 Flash via ``google-generativeai``)
or a test stub. Keeping this surface tiny means we never tangle orchestration
code with provider-specific quirks.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from app.config import get_settings

logger = logging.getLogger(__name__)


@runtime_checkable
class LLMClient(Protocol):
    """Contract every specialist depends on.

    Implementations MUST honor ``json_mode`` by configuring the provider to
    return a single JSON object when possible. The parser (``app.agents.parsers``)
    is still tolerant of fenced responses, but JSON mode keeps retries rare.
    """

    model_name: str

    def generate(self, *, system: str, user: str, json_mode: bool = True) -> str:
        ...


class GeminiLLMClient:
    """Google Gemini client built on ``google-generativeai``.

    The ``google.generativeai`` import is deferred to ``__init__`` so that
    simply importing this module does not require the SDK (useful when tests
    run without provider credentials installed).
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        *,
        api_key: str | None = None,
        temperature: float = 0.2,
    ) -> None:
        import google.generativeai as genai  # local import by design

        settings = get_settings()
        key = api_key or settings.gemini_api_key
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        genai.configure(api_key=key)

        self._genai = genai
        self.model_name: str = model
        self._temperature = temperature

    def generate(self, *, system: str, user: str, json_mode: bool = True) -> str:
        generation_config: dict = {"temperature": self._temperature}
        if json_mode:
            generation_config["response_mime_type"] = "application/json"

        model = self._genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system,
            generation_config=generation_config,
        )
        response = model.generate_content(user)

        text = getattr(response, "text", None)
        if not text:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                content = getattr(candidates[0], "content", None)
                parts = getattr(content, "parts", None) or []
                text = "".join(getattr(p, "text", "") for p in parts)
        if not text:
            raise RuntimeError(
                f"Gemini returned an empty response for model={self.model_name}"
            )
        return text
