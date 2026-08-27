"""Tool registry (SPEC.md §19). Each tool wraps an existing service
function — no new business logic, just a name + JSON schema + handler the
agent loop can call by name.

`run_workflow` from SPEC.md §19's full built-in tool list is deliberately
absent — workflows don't exist until Phase 13.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.modules.ai.providers import ToolSpec
from app.modules.documents import service as documents_service
from app.modules.ingestion import service as ingestion_service
from app.modules.search import service as search_service

logger = logging.getLogger("helix.agents")


@dataclass(frozen=True)
class ToolContext:
    db: AsyncSession
    org_id: uuid.UUID
    user_id: uuid.UUID


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: ToolHandler


async def _search_handler(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", ""))
    # Reuses search as-is (Phase 8), so ACL-aware filtering applies for
    # free — an agent can never retrieve content its triggering user
    # couldn't see themselves.
    results, _ = await search_service.search(
        ctx.db, ctx.org_id, ctx.user_id, query, limit=5, cursor=None
    )
    return {
        "results": [
            {
                "document_id": str(result.document_id),
                "document_title": result.document_title,
                "chunk_id": str(result.chunk_id),
                "snippet": result.snippet,
            }
            for result in results
        ]
    }


async def _fetch_document_handler(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    raw_id = str(args.get("document_id", ""))
    try:
        document_id = uuid.UUID(raw_id)
    except ValueError:
        return {"error": f"{raw_id!r} is not a valid document_id"}

    try:
        document = await documents_service.get_document(ctx.db, ctx.org_id, document_id)
    except NotFoundError:
        return {"error": "document not found"}

    content = await ingestion_service.get_document_content(ctx.db, ctx.org_id, document_id)
    return {"title": document.title, "content": content}


_ALLOWED_HTTP_METHODS = ("GET", "POST")


async def _http_request_handler(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url", ""))
    method = str(args.get("method", "GET")).upper()

    try:
        host = httpx.URL(url).host
    except httpx.InvalidURL:
        return {"error": f"{url!r} is not a valid URL"}

    settings = get_settings()
    # Default-deny (SPEC.md §29, CLAUDE.md §5): an empty/unconfigured
    # allowlist means every host is refused, never that every host is
    # allowed.
    if host not in settings.agent_http_allowlist:
        return {"error": f"host {host!r} is not on the http_request allowlist"}
    if method not in _ALLOWED_HTTP_METHODS:
        return {"error": f"method {method!r} is not permitted (use GET or POST)"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(method, url, content=args.get("body"))
    except httpx.HTTPError as exc:
        return {"error": f"request failed: {exc}"}

    return {
        "status_code": response.status_code,
        # Truncated: the response goes back into the LLM's context window
        # and is persisted verbatim in agent_steps.output — an unbounded
        # body would blow both budgets.
        "body": response.text[:4000],
    }


async def _notify_handler(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    # Traced no-op: real delivery is the `notifications` module, still a
    # Phase 15 stub. This records the intended notification (the
    # agent_steps row already persists this call's input/output) without
    # delivering it anywhere — never mistake a successful `notify` step for
    # an actually-sent notification before Phase 15 lands.
    logger.info("notify tool called (not delivered — Phase 15): %r", args)
    return {
        "status": "recorded_not_delivered",
        "channel": args.get("channel"),
        "message": args.get("message"),
    }


TOOLS: dict[str, Tool] = {
    "search": Tool(
        spec=ToolSpec(
            name="search",
            description="Search the organization's indexed documents for relevant passages.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The search query."}},
                "required": ["query"],
            },
        ),
        handler=_search_handler,
    ),
    "fetch_document": Tool(
        spec=ToolSpec(
            name="fetch_document",
            description="Fetch the full text of a specific document by its id.",
            parameters={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "The document's UUID."}
                },
                "required": ["document_id"],
            },
        ),
        handler=_fetch_document_handler,
    ),
    "http_request": Tool(
        spec=ToolSpec(
            name="http_request",
            description=(
                "Make an HTTP GET or POST request to an allowlisted host. Refused for any "
                "host not explicitly allowlisted by the organization."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "method": {"type": "string", "enum": list(_ALLOWED_HTTP_METHODS)},
                    "body": {"type": "string"},
                },
                "required": ["url"],
            },
        ),
        handler=_http_request_handler,
    ),
    "notify": Tool(
        spec=ToolSpec(
            name="notify",
            description=(
                "Record an intended notification for a channel and message. Does not "
                "deliver it anywhere yet."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "channel": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["channel", "message"],
            },
        ),
        handler=_notify_handler,
    ),
}
