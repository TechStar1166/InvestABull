"""Centralized runtime configuration.

All environment variables are read through this module so the rest of the code
base never touches ``os.environ`` directly. This keeps tests deterministic and
makes it obvious which knobs exist.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load backend/.env regardless of process cwd (e.g. uvicorn from repo root).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Process-wide configuration loaded from environment / .env."""

    # LLM providers
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(
        default="claude-sonnet-4-6",
        alias="ANTHROPIC_MODEL",
        description=(
            "Anthropic Messages API model id for the coordinator. "
            "Override via ANTHROPIC_MODEL in backend/.env (e.g. claude-3-5-sonnet-20241022)."
        ),
    )

    # Data providers
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    fred_api_key: str | None = Field(default=None, alias="FRED_API_KEY")
    sec_edgar_user_agent: str = Field(
        default="InvestABull Research <contact@example.com>",
        alias="SEC_EDGAR_USER_AGENT",
    )

    # RAG / storage
    chroma_persist_dir: Path = Field(default=Path("./.chroma"), alias="CHROMA_PERSIST_DIR")
    sec_filings_cache_dir: Path = Field(
        default=Path("./.sec_cache"), alias="SEC_FILINGS_CACHE_DIR"
    )
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL"
    )

    # Runtime
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    http_timeout_seconds: float = Field(default=20.0, alias="HTTP_TIMEOUT_SECONDS")
    http_max_retries: int = Field(default=3, alias="HTTP_MAX_RETRIES")

    model_config = SettingsConfigDict(
        env_file=_BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    Cached so that importing this module is cheap and all callers observe the
    same configuration, but still easy to override in tests by calling
    ``get_settings.cache_clear()``.
    """
    return Settings()  # type: ignore[call-arg]
