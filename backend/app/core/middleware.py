import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import request_id_var


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
