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

    # Agent runtime guardrails (SPEC.md §19) — hard-enforced in code, not
    # just prompted. agent_max_run_cost_usd is a per-*run* ceiling (aborts a
    # single pathological run); the org-wide monthly cap from ai-config
    # (ai_default_monthly_cost_cap_usd above / an org's override) is checked
    # separately, before a run is even enqueued.
    agent_max_steps: int = 8
    agent_run_timeout_seconds: int = 120
    agent_max_run_cost_usd: float = 1.0
    agent_max_job_attempts: int = 1
    # Default-deny (SPEC.md §29): empty means the http_request tool refuses
    # every host until explicit hostnames are added here.
    agent_http_allowlist: list[str] = []

    # Workflow engine guardrails (SPEC.md §20) -- hard-enforced in code, same
    # philosophy as the agent_* settings above. workflow_run_max_job_attempts
    # is intentionally > 1 (unlike agent_max_job_attempts): the executor is
    # explicitly designed to be safely resumable from persisted StepRun
    # state (see workflows/executor.py), so letting Arq retry a crashed
    # worker's run is the whole point, not a risk to avoid.
    workflow_step_max_attempts: int = 3
    workflow_step_backoff_base_seconds: int = 5  # attempt N waits base * 2**(N-1): 5s, 10s, 20s
    workflow_run_max_steps: int = 50
    workflow_run_timeout_seconds: int = 600
    workflow_run_max_job_attempts: int = 3
    workflow_ai_node_max_tool_rounds: int = 4

    # Connector framework (SPEC.md §26). connector_encryption_key must be a
    # valid Fernet key (Fernet.generate_key(), base64-encoded 32 bytes) --
    # never reuse the local-dev default outside local dev, same warning as
    # jwt_signing_keys above.
    connector_encryption_key: str = "THs3h55oNt0505SRw1YgPLKE0TlCB_fkSaxjfmg51GM="
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    github_oauth_redirect_url: str = "http://localhost:8000/api/v1/oauth/github/callback"
    connector_sync_interval_minutes: int = 15
    connector_sync_max_job_attempts: int = 3
    # Default-deny (SPEC.md §29), same posture as agent_http_allowlist but a
    # deliberately separate setting -- a connector's URL list is an
    # admin-authored, out-of-band decision at connect time, not something a
    # possibly-prompt-injected agent tool call can steer, so it legitimately
    # warrants a different (often broader) set of allowed hosts.
    connector_web_allowlist: list[str] = []
    # Where the GitHub OAuth callback redirects the browser back to once a
    # connector is connected -- matches CORSMiddleware's allowed origin in
    # app/main.py.
    frontend_url: str = "http://localhost:3000"

    # Notifications (SPEC.md §23). Defaults point at the local Mailpit
    # dev-catcher (docker-compose.yml) -- no account or cost needed for
    # local dev/testing; point these at a real provider's SMTP relay
    # (SendGrid/Postmark/SES/Resend all expose one) for a live deployment,
    # no code change required.
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    smtp_from_address: str = "notifications@helix.local"
    notification_max_job_attempts: int = 3
    # UTC hour the daily digest sweep runs at.
    notification_digest_hour: int = 9

    # Billing (SPEC.md §16, Phase 16). Test-mode Stripe keys are free --
    # create a Stripe account, stay in test mode, and use its sk_test_...
    # secret key. The webhook secret comes from `stripe listen` for local
    # dev, or the dashboard's webhook config for a deployed environment.
    # Price IDs are only needed to actually create a Checkout Session for
    # that plan; the free plan needs neither Stripe object.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_pro: str = ""
    stripe_price_id_enterprise: str = ""
    # Where Stripe Checkout redirects the browser back to on success/cancel.
    stripe_checkout_success_url: str = (
        "http://localhost:3000/orgs/{org_id}/billing?checkout=success"
    )
    stripe_checkout_cancel_url: str = (
        "http://localhost:3000/orgs/{org_id}/billing?checkout=cancelled"
    )

    # Public API & webhooks (SPEC.md §18, Phase 18). No paid service --
    # outbound webhook delivery is a plain httpx POST (already a dependency).
    public_api_rate_limit_max_requests: int = 60
    public_api_rate_limit_window_seconds: int = 60
    webhook_delivery_max_job_attempts: int = 5
    webhook_delivery_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
