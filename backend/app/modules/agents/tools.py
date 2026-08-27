"""Tool registry (SPEC.md §19). Each tool wraps an existing service
function — no new business logic, just a name + JSON schema + handler the
agent loop can call by name.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, QuotaExceededError
from app.modules.ai.providers import ToolSpec
from app.modules.documents import service as documents_service
from app.modules.ingestion import service as ingestion_service
from app.modules.notifications import service as notifications_service
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
    # Real delivery via the notifications module (Phase 15) -- fans out to
    # whichever channel(s) the recipient has enabled, per their own
    # preferences. No "channel" arg: a caller-supplied channel would let a
    # run bypass the recipient's preferences, which SPEC.md §23 explicitly
    # requires be respected.
    raw_user_id = args.get("user_id")
    try:
        recipient_id = uuid.UUID(str(raw_user_id)) if raw_user_id else ctx.user_id
    except ValueError:
        return {"error": f"{raw_user_id!r} is not a valid user_id"}

    message = str(args.get("message", ""))
    subject = str(args.get("subject") or (message[:80] + ("…" if len(message) > 80 else "")))

    try:
        notifications = await notifications_service.notify(
            ctx.db,
            ctx.org_id,
            recipient_id,
            event_type="notify.manual",
            payload={"subject": subject, "message": message},
        )
    except NotFoundError as exc:
        return {"error": str(exc)}
    return {"status": "queued", "notification_ids": [str(n.id) for n in notifications]}


async def _run_workflow_handler(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    # Deferred import: workflows/schemas.py imports this module (TOOLS) to
    # validate action/ai node tool names, so a top-level import here would
    # be circular. Importing inside the handler instead means the cycle
    # never exists at module-load time, only at call time once both
    # modules are already fully imported.
    from app.modules.workflows import service as workflows_service

    raw_id = str(args.get("workflow_id", ""))
    try:
        workflow_id = uuid.UUID(raw_id)
    except ValueError:
        return {"error": f"{raw_id!r} is not a valid workflow_id"}

    try:
        run = await workflows_service.create_run(
            ctx.db,
            ctx.org_id,
            workflow_id,
            {"type": "agent", "input": args.get("input", {})},
            triggered_by_user_id=ctx.user_id,
        )
    except (NotFoundError, ConflictError, QuotaExceededError) as exc:
        return {"error": str(exc)}
    return {"run_id": str(run.id), "status": run.status}


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
                "Send a notification to a user. Delivered on whichever channel(s) (email, "
                "in-app) the recipient has enabled for this kind of notification -- you "
                "cannot force a specific channel."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "The notification body."},
                    "subject": {
                        "type": "string",
                        "description": (
                            "Optional subject/title for email delivery; derived from "
                            "message if omitted."
                        ),
                    },
                    "user_id": {
                        "type": "string",
                        "description": (
                            "Optional recipient org member id. Defaults to the user "
                            "who triggered this run."
                        ),
                    },
                },
                "required": ["message"],
            },
        ),
        handler=_notify_handler,
    ),
    "run_workflow": Tool(
        spec=ToolSpec(
            name="run_workflow",
            description=(
                "Trigger a run of an existing workflow by its id, optionally with input data. "
                "Returns the new run's id and status; does not wait for it to finish."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string", "description": "The workflow's UUID."},
                    "input": {"type": "object", "description": "Arbitrary input for the run."},
                },
                "required": ["workflow_id"],
            },
        ),
        handler=_run_workflow_handler,
    ),
}
