import hashlib
import hmac
import json
import logging
import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.queue import enqueue_webhook_delivery
from app.core.security import hash_opaque_token
from app.core.tenancy import set_tenant_context
from app.modules.api.models import ApiKey, Webhook, WebhookDelivery
from app.modules.audit import service as audit_service
from app.modules.auth.models import User
from app.modules.events.models import DomainEvent

logger = logging.getLogger("helix.api")

_KEY_PREFIX = "hx_"


def _generate_raw_key() -> str:
    return f"{_KEY_PREFIX}{secrets.token_urlsafe(32)}"


# --- API keys ---


async def create_api_key(
    db: AsyncSession, org_id: uuid.UUID, actor: User, name: str, scopes: Sequence[str]
) -> tuple[ApiKey, str]:
    raw_key = _generate_raw_key()
    key = ApiKey(
        org_id=org_id,
        name=name,
        prefix=raw_key[:12],
        hash=hash_opaque_token(raw_key),
        scopes=list(scopes),
        created_by_user_id=actor.id,
    )
    db.add(key)
    await set_tenant_context(db, org_id)  # for the audit_logs insert below, not ApiKey itself
    await audit_service.record(
        db,
        org_id,
        actor.id,
        "api_key.created",
        resource_type="api_key",
        resource_id=key.id,
        metadata={"name": name, "scopes": scopes},
    )
    await db.commit()
    await db.refresh(key)
    return key, raw_key


async def list_api_keys(db: AsyncSession, org_id: uuid.UUID) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.org_id == org_id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(
    db: AsyncSession, org_id: uuid.UUID, key_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.org_id == org_id, ApiKey.revoked_at.is_(None)
        )
    )
    key = result.scalar_one_or_none()
    if key is None:
        raise NotFoundError("api key not found")
    key.revoked_at = datetime.now(UTC)
    await set_tenant_context(db, org_id)
    await audit_service.record(
        db, org_id, actor_id, "api_key.revoked", resource_type="api_key", resource_id=key_id
    )
    await db.commit()


async def resolve_api_key(db: AsyncSession, raw_key: str) -> ApiKey | None:
    """No tenant context set on purpose -- ApiKey carries no RLS policy
    (see its docstring). The hash lookup itself is the authorization."""
    if not raw_key.startswith(_KEY_PREFIX):
        return None
    result = await db.execute(
        select(ApiKey).where(ApiKey.hash == hash_opaque_token(raw_key), ApiKey.revoked_at.is_(None))
    )
    key = result.scalar_one_or_none()
    if key is None:
        return None
    key.last_used_at = datetime.now(UTC)
    await db.commit()
    return key


# --- webhooks ---


async def create_webhook(
    db: AsyncSession, org_id: uuid.UUID, actor: User, url: str, events: list[str]
) -> tuple[Webhook, str]:
    await set_tenant_context(db, org_id)
    secret = secrets.token_urlsafe(32)
    webhook = Webhook(
        org_id=org_id, url=url, secret=secret, events=events, created_by_user_id=actor.id
    )
    db.add(webhook)
    await audit_service.record(
        db,
        org_id,
        actor.id,
        "webhook.created",
        resource_type="webhook",
        resource_id=webhook.id,
        metadata={"url": url, "events": events},
    )
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(webhook)
    return webhook, secret


async def list_webhooks(db: AsyncSession, org_id: uuid.UUID) -> list[Webhook]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Webhook).where(Webhook.org_id == org_id).order_by(Webhook.created_at.desc())
    )
    return list(result.scalars().all())


async def deactivate_webhook(
    db: AsyncSession, org_id: uuid.UUID, webhook_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    """ "Delete" in the API sense -- stops future deliveries without erasing
    webhook_deliveries' history (their webhook_id FK would otherwise
    dangle, and the delivery log is the whole point of Phase 18's "deliver
    reliably" DoD)."""
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.org_id == org_id)
    )
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise NotFoundError("webhook not found")
    webhook.active = False
    await audit_service.record(
        db, org_id, actor_id, "webhook.deleted", resource_type="webhook", resource_id=webhook_id
    )
    await db.commit()


async def list_deliveries(
    db: AsyncSession, org_id: uuid.UUID, webhook_id: uuid.UUID
) -> list[WebhookDelivery]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.org_id == org_id, WebhookDelivery.webhook_id == webhook_id)
        .order_by(WebhookDelivery.created_at.desc())
    )
    return list(result.scalars().all())


# --- dispatch + delivery ---


async def dispatch_webhooks_for_event(
    db: AsyncSession, org_id: uuid.UUID, event_id: uuid.UUID
) -> None:
    """Called from api/tasks.py::dispatch_webhooks_for_event_task, itself
    enqueued by core/events.py::publish_event alongside (not instead of)
    workflows' own event-dispatch job -- two independent consumers of the
    same domain-event bus, each owned by its own module."""
    await set_tenant_context(db, org_id)
    event = await db.get(DomainEvent, event_id)
    if event is None:
        logger.error("domain event not found: %s", event_id)
        return

    result = await db.execute(
        select(Webhook).where(
            Webhook.org_id == org_id,
            Webhook.active.is_(True),
            Webhook.events.contains([event.type]),
        )
    )
    webhooks = list(result.scalars().all())
    for webhook in webhooks:
        delivery = WebhookDelivery(
            org_id=org_id, webhook_id=webhook.id, event_id=event.id, event_type=event.type
        )
        db.add(delivery)
        await db.flush()  # need delivery.id to enqueue before the commit below
        await enqueue_webhook_delivery(delivery.id, org_id)
    await db.commit()
    logger.info("dispatched event %s to %s webhook(s)", event_id, len(webhooks))


async def attempt_delivery(db: AsyncSession, org_id: uuid.UUID, delivery_id: uuid.UUID) -> None:
    """One HTTP attempt. Raises on any non-2xx/network failure so
    api/tasks.py::deliver_webhook_task's caller can retry via Arq --
    mirrors notifications/service.py::send_one's split (this function
    never marks a delivery "failed" itself; only the task layer knows
    whether this was the last attempt)."""
    await set_tenant_context(db, org_id)
    delivery = await db.get(WebhookDelivery, delivery_id)
    if delivery is None:
        logger.error("webhook delivery not found: %s", delivery_id)
        return
    webhook = await db.get(Webhook, delivery.webhook_id)
    event = await db.get(DomainEvent, delivery.event_id)
    if webhook is None or event is None:
        delivery.status = "failed"
        delivery.error = "webhook or source event no longer exists"
        await db.commit()
        return

    body = json.dumps(
        {
            "id": str(event.id),
            "type": event.type,
            "created_at": event.created_at.isoformat(),
            "data": event.payload,
        }
    ).encode()
    signature = hmac.new(webhook.secret.encode(), body, hashlib.sha256).hexdigest()

    delivery.attempts += 1
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=settings.webhook_delivery_timeout_seconds) as client:
            response = await client.post(
                webhook.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Helix-Signature": f"sha256={signature}",
                },
            )
        delivery.response_status = response.status_code
        response.raise_for_status()
    except Exception as exc:
        delivery.error = str(exc)
        await db.commit()
        raise

    delivery.status = "delivered"
    delivery.error = None
    await db.commit()


async def mark_delivery_failed(
    db: AsyncSession, org_id: uuid.UUID, delivery_id: uuid.UUID, error: str
) -> None:
    await set_tenant_context(db, org_id)
    delivery = await db.get(WebhookDelivery, delivery_id)
    if delivery is not None and delivery.status != "delivered":
        delivery.status = "failed"
        delivery.error = error
        await db.commit()
