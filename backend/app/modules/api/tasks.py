import logging
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.db import session_factory
from app.modules.api import service as api_service

logger = logging.getLogger("helix.api")


async def dispatch_webhooks_for_event_task(ctx: dict[str, Any], event_id: str, org_id: str) -> None:
    """Enqueued by core/events.py::publish_event -- fans one DomainEvent out
    to a WebhookDelivery row (+ its own delivery job) per matching active
    subscription."""
    async with session_factory() as db:
        await api_service.dispatch_webhooks_for_event(db, uuid.UUID(org_id), uuid.UUID(event_id))


async def deliver_webhook_task(ctx: dict[str, Any], delivery_id: str, org_id: str) -> None:
    """Registered with Arq, max_tries=settings.webhook_delivery_max_job_attempts
    -- same retry-via-re-raise shape as notifications/tasks.py::
    send_notification_task: only the final exhausted attempt marks the
    delivery "failed" rather than leaving it silently stuck as "pending".
    """
    settings = get_settings()
    delivery_uuid, org_uuid = uuid.UUID(delivery_id), uuid.UUID(org_id)
    current_try = ctx.get("job_try", 1)
    is_last_attempt = current_try >= settings.webhook_delivery_max_job_attempts

    try:
        async with session_factory() as db:
            await api_service.attempt_delivery(db, org_uuid, delivery_uuid)
    except Exception as exc:
        logger.warning("webhook delivery failed on attempt %s: %s", current_try, delivery_id)
        if is_last_attempt:
            async with session_factory() as db:
                await api_service.mark_delivery_failed(db, org_uuid, delivery_uuid, str(exc))
        raise
