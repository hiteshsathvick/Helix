import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue import enqueue_event_dispatch, enqueue_webhook_dispatch
from app.core.tenancy import set_tenant_context
from app.modules.events.models import DomainEvent


async def publish_event(
    db: AsyncSession,
    org_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    *,
    correlation_id: uuid.UUID | None = None,
) -> DomainEvent:
    """Publishes an internal domain event (SPEC.md §21) and immediately
    enqueues its dispatch to any matching workflow triggers — the same
    create-then-enqueue shape as ingestion.trigger_ingestion/agents.create_run,
    not a polling loop: the moment this call's caller knows an event
    happened is the moment dispatch is scheduled.

    Lives in app/core/ rather than inside any one module (events, ingestion,
    workflows, ...) since publishing is meant to be called from many
    modules and consumed by others — a genuinely cross-cutting concern, the
    same reason core/queue.py and core/tenancy.py live here rather than
    inside a single module.
    """
    event = DomainEvent(
        org_id=org_id,
        type=event_type,
        payload=payload,
        correlation_id=correlation_id or uuid.uuid4(),
    )
    db.add(event)
    await db.commit()
    # db.commit() ends the transaction, and with it the SET LOCAL/set_config
    # tenant context RLS needs — DomainEvent is RLS-protected, so refresh()
    # would otherwise come back empty (see agents/service.py's identical
    # lesson, hit and fixed in Phase 12).
    await set_tenant_context(db, org_id)
    await db.refresh(event)

    await enqueue_event_dispatch(event.id, org_id)
    # Independent of the workflow-trigger dispatch above -- see
    # enqueue_webhook_dispatch's own docstring.
    await enqueue_webhook_dispatch(event.id, org_id)
    return event
