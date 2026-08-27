from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "helix"
    environment: str = "local"
    # Low-privilege runtime role — see infra/docker/postgres-init/01-app-role.sql.
    # Must never be a superuser: superusers bypass Postgres Row-Level Security.
    database_url: str = "postgresql+asyncpg://helix_app:helix_app@postgres:5432/helix"
    # Owner/superuser role, used only by Alembic to run DDL.
    migrations_database_url: str = "postgresql+asyncpg://helix:helix@postgres:5432/helix"
    redis_url: str = "redis://redis:6379/0"
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "helix"
    s3_secret_key: str = "helix-secret"
    s3_bucket: str = "helix"
    documents_max_upload_bytes: int = 50 * 1024 * 1024

    # JWT signing keys, keyed by `kid`. The mechanism supports multiple
    # concurrently-valid keys (for future rotation); only one is active for
    # signing new tokens at a time.
    jwt_signing_keys: dict[str, str] = {"local-dev-key-1": "change-me-in-every-real-environment"}
    jwt_active_kid: str = "local-dev-key-1"
    jwt_access_token_ttl_minutes: int = 15
    jwt_refresh_token_ttl_days: int = 30

    auth_rate_limit_max_attempts: int = 5
    auth_rate_limit_window_seconds: int = 60

    # Phase 11 replaces this with the real swappable multi-provider
    # abstraction (SPEC.md §17); for now the pipeline needs *some* embedding
    # function, and this local CPU model is real semantic embeddings at zero
    # API cost — no key required.
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    ingestion_chunk_tokens: int = 800
    ingestion_chunk_overlap_tokens: int = 100
    ingestion_max_job_attempts: int = 3

    # Global default provider/model (SPEC.md §17). An org can override both
    # via PUT /orgs/{id}/ai-config (app/modules/ai) — these are just the
    # fallback when an org hasn't set its own.
    ai_default_provider: str = "anthropic"
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Ollama's local server speaks the OpenAI-compatible Chat Completions
    # API, so OpenAIProvider (app/modules/ai/providers.py) is reused against
    # this base_url instead of adding a second SDK.
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    ollama_model: str = "llama3.1"
    # None = unlimited. An org can set a stricter cap via its ai-config;
    # this is only the fallback for orgs that haven't (SPEC.md §17
    # "cost/limit guard"). This is a lightweight spend guard against
    # `messages.cost`, not the real metering system — that's usage_events
    # (Phase 27) and billing/subscriptions (Phase 16), which don't exist yet.
    ai_default_monthly_cost_cap_usd: float | None = None
    assistant_top_k: int = 6
    assistant_context_token_budget: int = 3000
    assistant_max_output_tokens: int = 1024
    # Bounds how much prior conversation gets replayed to the model each
    # turn — without this a long-running conversation's history would grow
    # its own (unbudgeted) token cost every single turn.
    assistant_max_history_messages: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
