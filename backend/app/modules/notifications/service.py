import base64
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.queue import enqueue_notification_send
from app.core.tenancy import set_tenant_context
from app.modules.auth import service as auth_service
from app.modules.notifications.models import Notification, NotificationPref
from app.modules.notifications.providers import get_email_provider
from app.modules.notifications.templates import render_template
from app.modules.orgs import service as orgs_service

logger = logging.getLogger("helix.notifications")

_CHANNELS = ("email", "in_app")


@dataclass(frozen=True)
class ResolvedPref:
    enabled: bool
    frequency: str  # "immediate" | "digest"


_DEFAULT_PREF = ResolvedPref(enabled=True, frequency="immediate")

# Every (channel, event) combination the preference center should always
# offer, defaults filled in even when no row exists yet -- keeps the
# frontend's list stable regardless of what a user has actually touched.
KNOWN_EVENTS = ("notify.manual", "connector.sync_failed")


async def resolve_prefs_for_user(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> dict[tuple[str, str], ResolvedPref]:
    """One query for every pref row this user has ever set -- callers fill
    in _DEFAULT_PREF for any (channel, event) absent from the result, so a
    single notify() call resolving one user's prefs across both channels
    never needs more than this one query, and the prefs GET endpoint can
    resolve every known combination from the same call.
    """
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(NotificationPref).where(
            NotificationPref.org_id == org_id, NotificationPref.user_id == user_id
        )
    )
    return {
        (row.channel, row.event): ResolvedPref(enabled=row.enabled, frequency=row.frequency)
        for row in result.scalars().all()
    }


async def get_resolved_prefs(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    resolved = await resolve_prefs_for_user(db, org_id, user_id)
    return [
        {
            "channel": channel,
            "event": event,
            **resolved.get((channel, event), _DEFAULT_PREF).__dict__,
        }
        for event in KNOWN_EVENTS
        for channel in _CHANNELS
    ]


async def update_prefs(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, updates: list[dict[str, Any]]
) -> None:
    await set_tenant_context(db, org_id)
    for update_item in updates:
        result = await db.execute(
            select(NotificationPref).where(
                NotificationPref.org_id == org_id,
                NotificationPref.user_id == user_id,
                NotificationPref.channel == update_item["channel"],
                NotificationPref.event == update_item["event"],
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = NotificationPref(
                org_id=org_id,
                user_id=user_id,
                channel=update_item["channel"],
                event=update_item["event"],
            )
            db.add(pref)
        pref.enabled = update_item["enabled"]
        pref.frequency = update_item["frequency"]
    await db.commit()


async def notify(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> list[Notification]:
    """The single entry point every notification-worthy call site uses
    (agents' notify tool, workflows' notify node, connectors' sync-failure
    path). Fans out to every channel the recipient has enabled for this
    event, per their own preferences -- the caller never picks a channel
    directly (SPEC.md §23: "unsubscribe/preference compliance is
    respected", which a caller-forced channel would defeat).

    In-app notifications are always immediate regardless of the recipient's
    frequency preference: "digest" is structurally an email-batching
    concept (the inbox itself already is the always-on aggregation view --
    a digest-delayed inbox would show yesterday's items late, defeating
    the point of an inbox).
    """
    await set_tenant_context(db, org_id)
    role = await orgs_service.get_membership_role(db, org_id, user_id)
    if role is None:
        raise NotFoundError(f"user {user_id} is not a member of this organization")

    prefs = await resolve_prefs_for_user(db, org_id, user_id)
    subject, body = render_template(event_type, payload)

    created: list[Notification] = []
    for channel in _CHANNELS:
        pref = prefs.get((channel, event_type), _DEFAULT_PREF)
        if not pref.enabled:
            continue
        immediate = channel == "in_app" or pref.frequency == "immediate"
        notification = Notification(
            org_id=org_id,
            user_id=user_id,
            channel=channel,
            event_type=event_type,
            template=event_type,
            payload=payload,
            subject=subject if channel == "email" else None,
            body=body,
            status="sent"
            if channel == "in_app"
            else ("pending" if immediate else "queued_for_digest"),
        )
        db.add(notification)
        created.append(notification)

    await db.commit()
    await set_tenant_context(db, org_id)
    for notification in created:
        await db.refresh(notification)
        if notification.channel == "email" and notification.status == "pending":
            await enqueue_notification_send(notification.id, org_id)

    logger.info(
        "notify: %s notification(s) created for user %s (event=%s)",
        len(created),
        user_id,
        event_type,
    )
    return created


async def send_one(db: AsyncSession, org_id: uuid.UUID, notification_id: uuid.UUID) -> None:
    """Delivers one pending email notification. Called from
    notifications/tasks.py::send_notification_task, which owns
    retry-via-re-raise (Arq's max_tries) and marking the row "failed" on
    the final exhausted attempt -- this function's job is just the send
    attempt and the row update on success.
    """
    await set_tenant_context(db, org_id)
    notification = await db.get(Notification, notification_id)
    if notification is None:
        logger.error("notification not found: %s", notification_id)
        return

    users_by_id = await auth_service.get_users_by_ids(db, [notification.user_id])
    recipient = users_by_id.get(notification.user_id)
    if recipient is None:
        notification.status = "failed"
        notification.error = "recipient user no longer exists"
        await db.commit()
        return

    provider = get_email_provider()
    await provider.send(
        to=recipient.email, subject=notification.subject or "", body=notification.body
    )
    notification.status = "sent"
    notification.error = None
    await db.commit()


async def send_digest_for_user(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, notifications: list[Notification]
) -> None:
    """One combined email for every queued_for_digest notification a user
    has, called from notifications/tasks.py::send_digest_task's per-user
    grouping loop. A simple line-per-notification list, not a fancy HTML
    digest layout, matching this phase's "boring, reviewable" template
    philosophy (notifications/templates.py)."""
    await set_tenant_context(db, org_id)
    users_by_id = await auth_service.get_users_by_ids(db, [user_id])
    recipient = users_by_id.get(user_id)
    if recipient is None:
        for notification in notifications:
            notification.status = "failed"
            notification.error = "recipient user no longer exists"
        await db.commit()
        return

    body = "\n\n".join(f"{n.subject}: {n.body}" for n in notifications)
    provider = get_email_provider()
    try:
        await provider.send(to=recipient.email, subject="Your daily digest", body=body)
    except Exception as exc:  # noqa: BLE001 -- leave queued for tomorrow's run to retry
        logger.exception("digest send failed for user %s", user_id)
        for notification in notifications:
            notification.error = str(exc)
        await db.commit()
        return

    for notification in notifications:
        notification.status = "sent"
        notification.error = None
    await db.commit()


def _encode_cursor(created_at: datetime, notification_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{notification_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if cursor is None:
        return None
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, id_str = raw.rsplit("|", 1)
    return datetime.fromisoformat(ts_str), uuid.UUID(id_str)


async def list_inbox(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, limit: int, cursor: str | None
) -> tuple[list[Notification], str | None]:
    """Keyset-paginated, not search/service.py's offset-in-disguise cursor
    -- an inbox is a live-inserting stream, where a new row arriving
    between two page fetches would shift every subsequent offset (skipping
    or duplicating a row); encoding (created_at, id) of the last-seen row
    instead makes each page's boundary independent of what's inserted
    after it.
    """
    await set_tenant_context(db, org_id)
    decoded = _decode_cursor(cursor)

    stmt = (
        select(Notification)
        .where(Notification.org_id == org_id, Notification.user_id == user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit + 1)
    )
    if decoded is not None:
        last_created_at, last_id = decoded
        stmt = stmt.where(
            tuple_(Notification.created_at, Notification.id) < (last_created_at, last_id)
        )

    rows = list((await db.execute(stmt)).scalars().all())
    page, has_more = rows[:limit], len(rows) > limit
    next_cursor = _encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
    return page, next_cursor


async def mark_read(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.org_id == org_id,
            Notification.user_id == user_id,
        )
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        raise NotFoundError("notification not found")
    notification.read_at = datetime.now(UTC)
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(notification)
    return notification


async def mark_all_read(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await set_tenant_context(db, org_id)
    await db.execute(
        update(Notification)
        .where(
            Notification.org_id == org_id,
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
