import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import tiktoken
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.tenancy import set_tenant_context
from app.modules.ai import cost_guard
from app.modules.ai import service as ai_service
from app.modules.ai.prompts import ASSISTANT_SYSTEM_PROMPT_CURRENT, NO_CONTEXT_PLACEHOLDER
from app.modules.assistant.models import Conversation, Message
from app.modules.assistant.schemas import Citation
from app.modules.ingestion import service as ingestion_service
from app.modules.search import service as search_service
from app.modules.search.schemas import SearchResult

logger = logging.getLogger("helix.assistant")

_encoding = tiktoken.get_encoding("cl100k_base")


@dataclass
class AnswerToken:
    text: str


@dataclass
class AnswerDone:
    message_id: uuid.UUID
    citations: list[Citation]


def _title_from_query(query: str) -> str:
    query = query.strip()
    return query if len(query) <= 60 else query[:57] + "..."


async def resolve_conversation(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    query: str,
) -> Conversation:
    """Called by the router *before* opening the SSE stream — a 404 raised
    here becomes a normal error response; raised from inside the streaming
    generator instead, it would land after the 200 status and headers are
    already committed, and couldn't be reported as a clean 404 at all.
    """
    await set_tenant_context(db, org_id)
    if conversation_id is not None:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.org_id == org_id,
                Conversation.user_id == user_id,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise NotFoundError("conversation not found")
        return conversation

    conversation = Conversation(org_id=org_id, user_id=user_id, title=_title_from_query(query))
    db.add(conversation)
    # Committed, not just flushed: the streaming generator that follows
    # opens its *own* session (router.py) — a flush alone is only visible
    # within this session's own uncommitted transaction, and NullPool
    # (core/db.py) means a fresh connection sees none of that.
    await db.commit()
    return conversation


def _assemble_context(
    results: list[SearchResult], contents: dict[uuid.UUID, str], token_budget: int
) -> tuple[str, list[SearchResult]]:
    parts: list[str] = []
    used: list[SearchResult] = []
    total_tokens = 0
    for i, result in enumerate(results, start=1):
        content = contents.get(result.chunk_id, "")
        piece = f"[{i}] {result.document_title}\n{content}"
        piece_tokens = len(_encoding.encode(piece))
        # Always keep at least the first (highest-ranked) chunk, even if it
        # alone exceeds the budget — an empty context is worse than a
        # slightly over-budget one.
        if used and total_tokens + piece_tokens > token_budget:
            break
        parts.append(piece)
        used.append(result)
        total_tokens += piece_tokens
    context = "\n\n".join(parts) if parts else NO_CONTEXT_PLACEHOLDER
    return context, used


async def _get_history(
    db: AsyncSession, org_id: uuid.UUID, conversation_id: uuid.UUID, limit: int | None = None
) -> list[Message]:
    await set_tenant_context(db, org_id)
    stmt = (
        select(Message)
        .where(Message.org_id == org_id, Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(reversed(result.scalars().all()))


async def _get_monthly_spend(db: AsyncSession, org_id: uuid.UUID) -> float:
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(Message.cost), 0.0)).where(
            Message.org_id == org_id, Message.created_at >= month_start
        )
    )
    return float(result.scalar_one())


async def assert_within_cost_cap(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Called by the router *before* opening the SSE stream — same reasoning
    as `resolve_conversation` above: a `QuotaExceededError` raised from
    inside the streaming generator would land after the 200 status and
    headers are already committed, and couldn't become a clean 402 at all.
    """
    await set_tenant_context(db, org_id)
    ai_config = await ai_service.resolve_org_ai_config(db, org_id)
    spent = await _get_monthly_spend(db, org_id)
    cost_guard.enforce_cost_cap(spent, ai_config.monthly_cost_cap_usd)


async def query(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    query_text: str,
) -> AsyncIterator[AnswerToken | AnswerDone]:
    settings = get_settings()
    await set_tenant_context(db, org_id)

    ai_config = await ai_service.resolve_org_ai_config(db, org_id)

    # Retrieve: reuse Phase 8 as-is, so ACL-aware filtering applies for
    # free — this is the only place document content enters the prompt.
    results, _ = await search_service.search(
        db, org_id, user_id, query_text, limit=settings.assistant_top_k, cursor=None
    )
    contents = await ingestion_service.get_chunk_contents(
        db, org_id, [result.chunk_id for result in results]
    )
    context, used_results = _assemble_context(
        results, contents, settings.assistant_context_token_budget
    )

    user_message = Message(
        org_id=org_id, conversation_id=conversation_id, role="user", content=query_text
    )
    db.add(user_message)
    # `onupdate=func.now()` (TimestampMixin) only fires when this row is
    # actually part of an UPDATE — inserting Message rows that merely
    # reference it doesn't touch it, so list_conversations' "most recently
    # active first" ordering would otherwise silently degrade into
    # creation-order. resolve_conversation (router.py) ran in a different
    # session, so the Conversation object needs loading fresh in this one.
    conversation = await db.get(Conversation, conversation_id)
    assert conversation is not None  # resolve_conversation already verified it exists
    conversation.updated_at = datetime.now(UTC)
    await db.commit()

    history = await _get_history(
        db, org_id, conversation_id, settings.assistant_max_history_messages
    )
    llm_messages = [{"role": message.role, "content": message.content} for message in history]
    system_prompt = ASSISTANT_SYSTEM_PROMPT_CURRENT.render(context=context)

    full_text = ""
    input_tokens = 0
    output_tokens = 0
    async for event in ai_service.stream_completion(
        system_prompt,
        llm_messages,
        settings.assistant_max_output_tokens,
        provider=ai_config.provider,
        model=ai_config.model,
    ):
        if isinstance(event, ai_service.TextDelta):
            full_text += event.text
            yield AnswerToken(event.text)
        else:
            input_tokens, output_tokens = event.input_tokens, event.output_tokens

    citations = [
        Citation(
            document_id=result.document_id,
            document_title=result.document_title,
            chunk_id=result.chunk_id,
            ordinal=result.ordinal,
            snippet=result.snippet,
        )
        for result in used_results
    ]
    cost = ai_service.compute_cost(ai_config.model, input_tokens, output_tokens)

    await set_tenant_context(db, org_id)
    assistant_message = Message(
        org_id=org_id,
        conversation_id=conversation_id,
        role="assistant",
        content=full_text,
        citations=[citation.model_dump(mode="json") for citation in citations],
        tokens=input_tokens + output_tokens,
        cost=cost,
    )
    db.add(assistant_message)
    await db.commit()

    # assistant_message.id is already known (UUIDPKMixin sets it client-side
    # via a Python default, not a DB-generated one), so no refresh needed
    # just to report it here.
    yield AnswerDone(message_id=assistant_message.id, citations=citations)


async def list_conversations(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> list[Conversation]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.org_id == org_id, Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_conversation_with_messages(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> tuple[Conversation, list[Message]]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.org_id == org_id,
            Conversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise NotFoundError("conversation not found")

    messages = await _get_history(db, org_id, conversation_id)
    return conversation, messages
