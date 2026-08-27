import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_factory
from app.core.deps import get_db
from app.modules.assistant import service
from app.modules.assistant.schemas import (
    ConversationRead,
    ConversationSummary,
    MessageRead,
    QueryRequest,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.orgs.dependencies import require_permission
from app.modules.orgs.system_roles import PERMISSION_DOCUMENTS_READ

router = APIRouter(prefix="/orgs/{org_id}/assistant", tags=["assistant"])
conversations_router = APIRouter(prefix="/orgs/{org_id}/conversations", tags=["assistant"])


async def _sse_events(
    org_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID, query_text: str
) -> AsyncIterator[str]:
    # A dedicated session, opened and closed entirely within this
    # generator's own execution — not the router's `Depends(get_db)`
    # session. Exactly when FastAPI/Starlette tear down a yield-dependency
    # relative to a StreamingResponse's body iterating is subtle enough
    # (and, combined with NullPool — core/db.py — costly enough to get
    # wrong: a released connection means a *new* one next use, silently
    # losing anything only flushed, not committed) that relying on it
    # surviving the whole stream isn't worth it.
    async with session_factory() as db:
        async for event in service.query(db, org_id, user_id, conversation_id, query_text):
            payload: dict[str, Any]
            if isinstance(event, service.AnswerToken):
                payload = {"type": "token", "text": event.text}
            else:
                payload = {
                    "type": "done",
                    "conversation_id": str(conversation_id),
                    "message_id": str(event.message_id),
                    "citations": [citation.model_dump(mode="json") for citation in event.citations],
                }
            yield f"data: {json.dumps(payload)}\n\n"


@router.post("/query")
async def query_assistant(
    request: QueryRequest,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_DOCUMENTS_READ)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    # Resolved and *committed* (not just flushed — see _sse_events) before
    # the stream opens: a NotFoundError raised here becomes a normal 404;
    # raised from inside the generator instead, it would land after the
    # 200 status and headers are already sent, and couldn't be a clean 404
    # at all.
    conversation = await service.resolve_conversation(
        db, org_id, current_user.id, request.conversation_id, request.query
    )
    # Also resolved and enforced before the stream opens, for the same
    # reason as resolve_conversation: see service.assert_within_cost_cap.
    await service.assert_within_cost_cap(db, org_id)
    return StreamingResponse(
        _sse_events(org_id, current_user.id, conversation.id, request.query),
        media_type="text/event-stream",
    )


@conversations_router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_DOCUMENTS_READ)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationSummary]:
    conversations = await service.list_conversations(db, org_id, current_user.id)
    return [ConversationSummary.model_validate(conversation) for conversation in conversations]


@conversations_router.get("/{conversation_id}", response_model=ConversationRead)
async def get_conversation(
    conversation_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_DOCUMENTS_READ)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    conversation, messages = await service.get_conversation_with_messages(
        db, org_id, current_user.id, conversation_id
    )
    return ConversationRead(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageRead.model_validate(message) for message in messages],
    )
