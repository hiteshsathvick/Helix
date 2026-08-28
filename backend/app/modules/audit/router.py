import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.modules.audit import service
from app.modules.audit.schemas import AuditLogListResponse
from app.modules.orgs.dependencies import require_permission
from app.modules.orgs.system_roles import PERMISSION_AUDIT_READ

router = APIRouter(prefix="/orgs/{org_id}/audit", tags=["audit"])


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_AUDIT_READ)),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    results, next_cursor = await service.list_audit_logs(
        db, org_id, limit=limit, cursor=cursor, action=action, resource_type=resource_type
    )
    return AuditLogListResponse(results=results, next_cursor=next_cursor)
