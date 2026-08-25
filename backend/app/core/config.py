from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "helix"
    environment: str = "local"
    database_url: str = "postgresql+asyncpg://helix:helix@postgres:5432/helix"
    redis_url: str = "redis://redis:6379/0"
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "helix"
    s3_secret_key: str = "helix-secret"
    s3_bucket: str = "helix"


@lru_cache
def get_settings() -> Settings:
    return Settings()
