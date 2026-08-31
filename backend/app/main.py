from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api_v1.router import router as api_v1_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware, SecurityHeadersMiddleware
from app.core.secrets_guard import check_no_insecure_defaults
from app.core.storage import ensure_bucket_exists


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

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

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

    return app


app = create_app()
