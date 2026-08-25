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


@lru_cache
def get_settings() -> Settings:
    return Settings()
