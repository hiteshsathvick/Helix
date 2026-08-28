import base64
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import set_tenant_context
from app.modules.audit.models import AuditLog
from app.modules.audit.schemas import AuditLogRead
from app.modules.auth import service as auth_service


async def record(
    db: AsyncSession,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    *,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Adds the row and lets the caller's own already-imminent commit
    persist it -- same piggyback shape as billing/service.py::record_usage,
    and for the same reason: every call site is one line inserted right
    before a commit that was already about to happen, not a new round
    trip. Callers must already have this session's tenant context set for
    org_id (true at every instrumented call site -- each is deep inside an
    already org-scoped flow).
    """
    db.add(
        AuditLog(
            org_id=org_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_=metadata or {},
        )
    )


def _encode_cursor(created_at: datetime, log_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{log_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if cursor is None:
        return None
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, id_str = raw.rsplit("|", 1)
    return datetime.fromisoformat(ts_str), uuid.UUID(id_str)


async def list_audit_logs(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    limit: int,
    cursor: str | None,
    action: str | None = None,
    resource_type: str | None = None,
) -> tuple[list[AuditLogRead], str | None]:
    """Keyset-paginated (same reasoning as notifications' inbox: an
    audit log is a live-inserting stream, so an offset would skip or
    duplicate rows as new events land between page fetches)."""
    await set_tenant_context(db, org_id)
    decoded = _decode_cursor(cursor)

    stmt = (
        select(AuditLog)
        .where(AuditLog.org_id == org_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit + 1)
    )
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type is not None:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if decoded is not None:
        last_created_at, last_id = decoded
        stmt = stmt.where(tuple_(AuditLog.created_at, AuditLog.id) < (last_created_at, last_id))

    rows = list((await db.execute(stmt)).scalars().all())
    page, has_more = rows[:limit], len(rows) > limit
    next_cursor = _encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None

    actor_ids = [row.actor_id for row in page if row.actor_id is not None]
    users_by_id = await auth_service.get_users_by_ids(db, actor_ids)
    results = [
        AuditLogRead(
            id=row.id,
            actor_id=row.actor_id,
            actor_email=users_by_id[row.actor_id].email if row.actor_id in users_by_id else None,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            metadata=row.metadata_,
            created_at=row.created_at,
        )
        for row in page
    ]
    return results, next_cursor


async def count_distinct_actors_since(db: AsyncSession, org_id: uuid.UUID, since: datetime) -> int:
    """Analytics' "active users" figure: members who performed at least
    one audited action in the window, not just members who exist."""
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(func.count(func.distinct(AuditLog.actor_id))).where(
            AuditLog.org_id == org_id, AuditLog.created_at >= since, AuditLog.actor_id.is_not(None)
        )
    )
    return int(result.scalar_one())
