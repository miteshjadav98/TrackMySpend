"""Application settings, loaded from environment variables (12-factor).

Every tunable lives here so behaviour changes are configuration, not code. Secrets are
`SecretStr` so they never appear in logs or reprs. In deployed environments the values
come from Secret Manager via Cloud Run environment bindings.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
ThinkingLevel = Literal["minimal", "low", "medium", "high"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- service ----------------------------------------------------------------------
    environment: Environment = "local"
    service_name: str = "moneymoney-api"
    log_level: str = "INFO"
    log_json: bool = True

    # --- PostgreSQL (financial records, chat history, workflow checkpoints) ----------
    database_url: SecretStr = SecretStr(
        "postgresql://moneymoney:moneymoney@localhost:5432/moneymoney"
    )
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=5, ge=0)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0)
    database_statement_timeout_ms: int = Field(default=5_000, ge=100)
    # Prepared statements break behind transaction-mode poolers (PgBouncer, Cloud SQL
    # managed pooling). Off by default; enable only for direct connections.
    database_prepared_statements: bool = False
    checkpoint_pool_min_size: int = Field(default=1, ge=1)
    checkpoint_pool_max_size: int = Field(default=5, ge=1)

    # --- Redis (cache, rate limits, short-lived locks; never authoritative) ----------
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    redis_socket_timeout_seconds: float = Field(default=0.5, gt=0)
    redis_key_prefix: str = "mm"

    # --- auth / sessions --------------------------------------------------------------
    session_cookie_name: str = "mm_session"
    session_ttl_days: int = Field(default=30, ge=1)
    cookie_secure: bool = True
    cookie_domain: str | None = None
    # Comma-separated in the environment: ALLOWED_ORIGINS=https://a.example,https://b.example
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    password_min_length: int = Field(default=10, ge=8)
    # Where the web app is served; emailed links (password reset) point here.
    web_base_url: str = "http://localhost:3000"

    # --- rate limits (per user / per IP, fixed window) --------------------------------
    rate_limit_login_per_minute: int = 10
    rate_limit_register_per_hour: int = 20
    rate_limit_chat_per_minute: int = 20
    rate_limit_chat_per_day: int = 500
    # Each reset request sends an email, so these keep the feature from spamming anyone.
    rate_limit_password_reset_per_email_per_hour: int = 5
    rate_limit_password_reset_per_ip_per_hour: int = 20

    # --- LLM (Gemini on Vertex AI) ----------------------------------------------------
    llm_provider: Literal["gemini", "rules"] = "rules"
    gcp_project: str | None = None
    # Gemini 3.x models are served from the global / multi-region endpoints.
    vertex_location: str = "global"
    # Model selection per task, from the eval set (tests/evals, repeated runs, 2026-10-25):
    #   flash-lite + "minimal": 51% accurate        -> not usable
    #   flash-lite + "low":     87% raw; 78/78 with workflows/reconcile.py, p50 1.26 s, p90 1.65 s
    #   3.8-flash  + "low":     100%, but p50 2.3 s and a 35 s tail -> too slow for chat
    llm_understand_model: str = "gemini-3.5-flash-lite"
    llm_understand_thinking: ThinkingLevel = "low"
    llm_reply_model: str = "gemini-3.5-flash-lite"
    llm_reply_thinking: ThinkingLevel = "minimal"
    llm_timeout_seconds: float = Field(default=12.0, gt=0)  # per attempt
    llm_max_retries: int = Field(default=1, ge=0)
    # Hard ceiling per call, retries included, before degrading to the rules engine.
    llm_total_budget_seconds: float = Field(default=20.0, gt=0)
    # When Gemini is unavailable, fall back to the deterministic parser instead of failing.
    llm_fallback_to_rules: bool = True

    # --- agent runtime ----------------------------------------------------------------
    # "exit" writes one checkpoint per turn. Safe here because the only side effect
    # (saving transactions) is idempotent; see docs/architecture.md.
    agent_checkpoint_durability: Literal["sync", "async", "exit"] = "exit"
    agent_history_window: int = Field(default=8, ge=0, le=50)
    agent_max_clarification_rounds: int = Field(default=5, ge=1, le=20)
    agent_turn_timeout_seconds: float = Field(default=60.0, gt=0)
    agent_max_input_chars: int = Field(default=2_000, ge=100)
    agent_pending_ttl_hours: int = Field(default=24, ge=1)
    agent_recursion_limit: int = Field(default=40, ge=10)

    # --- cache --------------------------------------------------------------------------
    cache_summary_ttl_seconds: int = Field(default=600, ge=10)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production_like(self) -> bool:
        return self.environment in ("staging", "production")

    @property
    def sqlalchemy_url(self) -> str:
        """Async SQLAlchemy URL using the psycopg 3 driver."""
        url = self.database_url.get_secret_value()
        for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        raise ValueError("DATABASE_URL must be a postgresql:// URL")

    @property
    def psycopg_conninfo(self) -> str:
        """Plain libpq URL for psycopg (used by the LangGraph checkpointer pool)."""
        return self.sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
