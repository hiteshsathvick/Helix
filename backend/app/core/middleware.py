import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.request_context import request_id_var

_STATIC_SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
    # The API only ever returns JSON, never HTML -- 'none' is deliberately
    # maximally strict rather than something scoped to a frontend origin.
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
)
_HSTS_HEADER = (b"strict-transport-security", b"max-age=63072000; includeSubDomains")


class SecurityHeadersMiddleware:
    """Pure ASGI, same reasoning as RequestIDMiddleware below: needs to wrap
    `send` directly so it works for StreamingResponse (the assistant's SSE
    endpoint) as well as ordinary responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # HSTS on plain local HTTP would just be a lie the browser can't
        # act on (no TLS to pin to), so it's only added for non-local
        # environments, which are expected to sit behind TLS termination
        # (SPEC.md §36).
        settings = get_settings()
        extra_headers: tuple[tuple[bytes, bytes], ...] = _STATIC_SECURITY_HEADERS
        if settings.environment != "local":
            extra_headers = (*_STATIC_SECURITY_HEADERS, _HSTS_HEADER)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *extra_headers]
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RequestIDMiddleware:
    """Pure ASGI, not BaseHTTPMiddleware: BaseHTTPMiddleware runs the
    downstream app in a separate task and reconstructs the response before
    `dispatch` returns, which tears down `Depends(yield)` dependencies
    (e.g. the DB session) as soon as the route handler returns — before a
    StreamingResponse's body generator has actually run. The assistant's
    SSE endpoint (Phase 10) needs its DB session to stay open for the
    duration of the stream, so this had to change from BaseHTTPMiddleware
    to avoid that.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        request_id = headers.get(b"x-request-id", b"").decode() or str(uuid.uuid4())
        token = request_id_var.set(request_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)
