import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.notifications import service
from app.modules.notifications.schemas import (
    NotificationInboxResponse,
    NotificationPrefRead,
    NotificationPrefsUpdateRequest,
    NotificationRead,
)
from app.modules.orgs.dependencies import require_org_member

# Every endpoint here is a user managing their own data -- self-scoped via
# require_org_member (membership + RLS context) + current_user.id, the
# exact pattern orgs/router.py's "/me" endpoint already establishes for
# "any org member can access this, scoped to themselves." No new
# notifications:* permission: nothing here touches another user's data or
# org configuration.
router = APIRouter(prefix="/orgs/{org_id}/notifications", tags=["notifications"])


@router.get("", response_model=NotificationInboxResponse)
async def list_inbox(
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = Query(None),
    org_id: uuid.UUID = Depends(require_org_member),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationInboxResponse:
    results, next_cursor = await service.list_inbox(db, org_id, current_user.id, limit, cursor)
    return NotificationInboxResponse(
        results=[NotificationRead.model_validate(n) for n in results], next_cursor=next_cursor
    )


@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_read(
    notification_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_member),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationRead:
    notification = await service.mark_read(db, org_id, current_user.id, notification_id)
    return NotificationRead.model_validate(notification)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    org_id: uuid.UUID = Depends(require_org_member),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.mark_all_read(db, org_id, current_user.id)


prefs_router = APIRouter(prefix="/orgs/{org_id}/notification-prefs", tags=["notifications"])


@prefs_router.get("", response_model=list[NotificationPrefRead])
async def get_prefs(
    org_id: uuid.UUID = Depends(require_org_member),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationPrefRead]:
    resolved = await service.get_resolved_prefs(db, org_id, current_user.id)
    return [NotificationPrefRead.model_validate(pref) for pref in resolved]


@prefs_router.put("", response_model=list[NotificationPrefRead])
async def update_prefs(
    body: NotificationPrefsUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_member),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationPrefRead]:
    await service.update_prefs(db, org_id, current_user.id, body.as_dicts())
    resolved = await service.get_resolved_prefs(db, org_id, current_user.id)
    return [NotificationPrefRead.model_validate(pref) for pref in resolved]
