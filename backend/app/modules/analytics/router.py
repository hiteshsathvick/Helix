import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.modules.analytics import service
from app.modules.analytics.schemas import AnalyticsOverview
from app.modules.orgs.dependencies import require_permission
from app.modules.orgs.system_roles import PERMISSION_ANALYTICS_READ

router = APIRouter(prefix="/orgs/{org_id}/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
async def get_overview(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_ANALYTICS_READ)),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsOverview:
    return await service.get_overview(db, org_id)
