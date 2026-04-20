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
    filings_read_only: bool = Field(
        default=False,
        alias="FILINGS_READ_ONLY",
        description=(
            "When true, the /research request path never ingests 10-Ks on demand; "
            "it only queries Chroma. Tickers that were not pre-ingested return "
            "a NO_DATA filings envelope. Use this in production with a scheduled "
            "pre-ingestion job (see `python -m app.rag.cli ingest ...`)."
        ),
    )

    # News / Tavily speed tuning
    tavily_search_depth: str = Field(
        default="basic",
        alias="TAVILY_SEARCH_DEPTH",
        description="Tavily search_depth: 'basic' (fast) or 'advanced' (slower, richer).",
    )
    tavily_max_results: int = Field(
        default=5,
        alias="TAVILY_MAX_RESULTS",
        description="Max Tavily articles per query. Lower = faster + smaller LLM payload.",
    )
    tavily_days_back: int = Field(
        default=7,
        alias="TAVILY_DAYS_BACK",
        description="Tavily news recency window in days.",
    )
    tavily_cache_ttl_seconds: int = Field(
        default=600,
        alias="TAVILY_CACHE_TTL_SECONDS",
        description=(
            "TTL for in-memory Tavily result cache. 0 disables caching. "
            "Cache key: (ticker, days_back, max_results, company_name, search_depth)."
        ),
    )
    news_llm_max_articles: int = Field(
        default=5,
        alias="NEWS_LLM_MAX_ARTICLES",
        description=(
            "Keep at most this many articles (top by relevance_score) before "
            "sending to the News specialist LLM."
        ),
    )
    news_llm_include_snippet: bool = Field(
        default=False,
        alias="NEWS_LLM_INCLUDE_SNIPPET",
        description=(
            "When false, article snippets are dropped from the News LLM payload "
            "(saves hundreds to thousands of tokens per request)."
        ),
    )
    news_llm_snippet_chars: int = Field(
        default=300,
        alias="NEWS_LLM_SNIPPET_CHARS",
        description="Max chars per snippet when news_llm_include_snippet=true.",
    )

    # Macro / FRED speed tuning
    fred_max_workers: int = Field(
        default=4,
        alias="FRED_MAX_WORKERS",
        description=(
            "Thread pool size for parallelizing FRED series fetches inside "
            "fetch_macro_bundle. 0 or 1 forces sequential fetch."
        ),
    )
    fred_bundle_cache_ttl_seconds: int = Field(
        default=6 * 3600,
        alias="FRED_BUNDLE_CACHE_TTL_SECONDS",
        description=(
            "TTL for the in-memory macro-bundle cache, keyed on the tuple of "
            "series ids. FRED indicators are daily/weekly/monthly so a multi-hour "
            "TTL removes almost all macro latency across requests. 0 disables."
        ),
    )
    fred_series_info_cache_ttl_seconds: int = Field(
        default=24 * 3600,
        alias="FRED_SERIES_INFO_CACHE_TTL_SECONDS",
        description=(
            "TTL for cached FRED series metadata (title/units/frequency). "
            "Metadata almost never changes so a 24h default is safe. 0 disables."
        ),
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
