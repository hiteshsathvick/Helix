import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.tenancy import set_tenant_context
from app.modules.notifications import service as notifications_service
from app.modules.notifications.models import Notification
from app.modules.orgs import service as orgs_service

logger = logging.getLogger("helix.notifications")


async def send_notification_task(ctx: dict[str, Any], notification_id: str, org_id: str) -> None:
    """Registered with Arq (app/workers/run.py),
    max_tries=settings.notification_max_job_attempts. Retry is Arq's own
    re-invocation (re-raising below triggers it), same shape as
    connectors/tasks.py::sync_connector_task -- only the final exhausted
    attempt marks the row "failed" rather than leaving it silently stuck.
    """
    settings = get_settings()
    notification_uuid, org_uuid = uuid.UUID(notification_id), uuid.UUID(org_id)
    current_try = ctx.get("job_try", 1)
    is_last_attempt = current_try >= settings.notification_max_job_attempts

    try:
        async with session_factory() as db:
            await notifications_service.send_one(db, org_uuid, notification_uuid)
    except Exception as exc:
        logger.exception("notification send failed on attempt %s: %s", current_try, notification_id)
        if is_last_attempt:
            async with session_factory() as db:
                await set_tenant_context(db, org_uuid)
                notification = await db.get(Notification, notification_uuid)
                if notification is not None and notification.status != "sent":
                    notification.status = "failed"
                    notification.error = str(exc)
                    await db.commit()
        raise


async def send_digest_task(ctx: dict[str, Any]) -> None:
    """The arq cron entry (WorkerSettings.cron_jobs) driving SPEC.md §23's
    "batching/digests" -- once daily, gathers every org's
    queued_for_digest notifications, groups by recipient, and sends one
    combined email per user. Reuses the exact platform-wide-sweep shape
    connectors/tasks.py::sweep_connector_syncs_task already established.
    """
    sent_for_users = 0
    async with session_factory() as db:
        org_ids = await orgs_service.list_all_org_ids(db)
        for org_id in org_ids:
            await set_tenant_context(db, org_id)
            result = await db.execute(
                select(Notification).where(
                    Notification.org_id == org_id, Notification.status == "queued_for_digest"
                )
            )
            by_user: dict[uuid.UUID, list[Notification]] = {}
            for notification in result.scalars().all():
                by_user.setdefault(notification.user_id, []).append(notification)

            for user_id, notifications in by_user.items():
                await notifications_service.send_digest_for_user(db, org_id, user_id, notifications)
                sent_for_users += 1

    logger.info("notification digest sweep: sent for %s user(s)", sent_for_users)
