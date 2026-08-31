import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from app.api_v1.router import router as api_v1_router
from app.core.config import get_settings
from app.core.db import engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware, SecurityHeadersMiddleware
from app.core.redis import get_redis_client
from app.core.secrets_guard import check_no_insecure_defaults
from app.core.storage import ensure_bucket_exists
from app.core.tracing import configure_tracing

logger = logging.getLogger("helix.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # MinIO doesn't create the configured bucket on its own.
    await ensure_bucket_exists()
    yield


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    # Fail fast and loud rather than boot a non-local deployment that's
    # silently still signing tokens / encrypting connector secrets with the
    # committed local-dev defaults (SPEC.md §29, CLAUDE.md §5).
    check_no_insecure_defaults(settings)

    configure_tracing(settings.otel_service_name)
    # Opt-in (SPEC.md §30): only initialized if a real DSN is configured,
    # same pattern as stripe_secret_key/github_oauth_client_id -- nothing
    # here requires a Sentry account to exist.
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready,metrics")
    # exclude_default_metrics=False keeps the built-in request duration/
    # count/in-progress metrics; .expose() is what actually adds GET
    # /metrics -- the two-call shape is this library's own API.
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
        allow_credentials=True,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)
    app.include_router(api_v1_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        # Liveness (/health) only proves the process is up; orchestrators
        # (k8s, Fly.io -- SPEC.md §30) need readiness to also prove the two
        # things every request actually depends on are reachable, so a
        # container isn't routed traffic before/after it can serve it.
        checks = {"database": False, "redis": False}
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            logger.exception("readiness check failed: database")
        redis_client = get_redis_client()
        try:
            await redis_client.ping()
            checks["redis"] = True
        except Exception:
            logger.exception("readiness check failed: redis")
        finally:
            await redis_client.aclose()

        ready_status = all(checks.values())
        return JSONResponse(
            status_code=200 if ready_status else 503,
            content={"status": "ready" if ready_status else "not ready", "checks": checks},
        )

    return app


app = create_app()
