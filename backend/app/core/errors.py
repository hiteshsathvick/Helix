import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.core.request_context import request_id_var

logger = logging.getLogger("helix.errors")


class HelixError(Exception):
    """Base for domain errors. Subclass per failure mode with a stable `code`
    and `status_code` — never raise this directly."""

    code = "internal_error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(HelixError):
    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND


class ValidationError(HelixError):
    code = "validation_error"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


class ConflictError(HelixError):
    code = "conflict"
    status_code = status.HTTP_409_CONFLICT


class UnauthorizedError(HelixError):
    code = "unauthorized"
    status_code = status.HTTP_401_UNAUTHORIZED


class ForbiddenError(HelixError):
    code = "forbidden"
    status_code = status.HTTP_403_FORBIDDEN


class RateLimitedError(HelixError):
    code = "rate_limited"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS


class PayloadTooLargeError(HelixError):
    code = "payload_too_large"
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


class QuotaExceededError(HelixError):
    code = "quota_exceeded"
    status_code = status.HTTP_402_PAYMENT_REQUIRED


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def helix_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HelixError)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(exc.code, exc.message, exc.details),
    )


def _json_safe_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Pydantic v2 embeds the raised exception itself in each error's `ctx`
    (e.g. `ctx: {"error": ValueError("...")}` for a `field_validator` that
    raises `ValueError`) — never JSON-serializable, and `msg` already carries
    the same human-readable text, so `ctx` is dropped rather than encoded.
    """
    return [{k: v for k, v in dict(error).items() if k != "ctx"} for error in errors]


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_envelope(
            "validation_error",
            "Request validation failed",
            {"errors": _json_safe_errors(exc.errors())},
        ),
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope("http_error", str(exc.detail)),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = request_id_var.get()
    logger.exception("unhandled exception")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope(
            "internal_error",
            "An unexpected error occurred",
            {"correlation_id": correlation_id},
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HelixError, helix_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
