import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.modules.ai import service
from app.modules.ai.schemas import OrgAIConfigRead, OrgAIConfigUpdate
from app.modules.orgs.dependencies import require_org_member, require_permission
from app.modules.orgs.system_roles import PERMISSION_AI_CONFIG_MANAGE

router = APIRouter(prefix="/orgs/{org_id}/ai-config", tags=["ai"])


def _to_read(config: service.OrgAIConfig) -> OrgAIConfigRead:
    return OrgAIConfigRead(
        provider=config.provider,
        model=config.model,
        monthly_cost_cap_usd=config.monthly_cost_cap_usd,
    )


@router.get("", response_model=OrgAIConfigRead)
async def get_ai_config(
    org_id: uuid.UUID = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
) -> OrgAIConfigRead:
    return _to_read(await service.resolve_org_ai_config(db, org_id))


@router.put("", response_model=OrgAIConfigRead)
async def update_ai_config(
    body: OrgAIConfigUpdate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_AI_CONFIG_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> OrgAIConfigRead:
    return _to_read(await service.update_org_ai_config(db, org_id, body))
