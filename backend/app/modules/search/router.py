import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.orgs.dependencies import require_permission
from app.modules.orgs.system_roles import PERMISSION_DOCUMENTS_READ
from app.modules.search import service
from app.modules.search.schemas import SearchResponse

router = APIRouter(prefix="/orgs/{org_id}/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def search_documents(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = Query(None),
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_DOCUMENTS_READ)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    results, next_cursor = await service.search(db, org_id, current_user.id, q, limit, cursor)
    return SearchResponse(results=results, next_cursor=next_cursor)
