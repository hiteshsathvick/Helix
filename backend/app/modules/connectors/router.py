import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.connectors import service
from app.modules.connectors.schemas import (
    ConnectorRead,
    GitHubAuthorizeResponse,
    WebConnectorCreate,
)
from app.modules.orgs.dependencies import require_permission
from app.modules.orgs.system_roles import PERMISSION_CONNECTORS_MANAGE

router = APIRouter(prefix="/orgs/{org_id}/connectors", tags=["connectors"])


@router.post("", response_model=ConnectorRead, status_code=status.HTTP_201_CREATED)
async def create_web_connector(
    body: WebConnectorCreate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_CONNECTORS_MANAGE)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConnectorRead:
    source = await service.create_web_connector(
        db, org_id, current_user.id, body.name, body.url_list
    )
    return ConnectorRead.model_validate(source)


@router.get("", response_model=list[ConnectorRead])
async def list_connectors(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_CONNECTORS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> list[ConnectorRead]:
    sources = await service.list_connectors(db, org_id)
    return [ConnectorRead.model_validate(source) for source in sources]


@router.get("/github/authorize", response_model=GitHubAuthorizeResponse)
async def github_authorize(
    repo: str = Query(..., description='"owner/name"'),
    branch: str = Query("main"),
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_CONNECTORS_MANAGE)),
    current_user: User = Depends(get_current_user),
) -> GitHubAuthorizeResponse:
    url = service.start_github_oauth(org_id, current_user.id, repo, branch)
    return GitHubAuthorizeResponse(authorize_url=url)


@router.get("/{source_id}", response_model=ConnectorRead)
async def get_connector(
    source_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_CONNECTORS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> ConnectorRead:
    source = await service.get_connector(db, org_id, source_id)
    return ConnectorRead.model_validate(source)


@router.post(
    "/{source_id}/sync", response_model=ConnectorRead, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_sync(
    source_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_CONNECTORS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> ConnectorRead:
    source = await service.trigger_sync(db, org_id, source_id)
    return ConnectorRead.model_validate(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_connector(
    source_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_CONNECTORS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.disconnect_connector(db, org_id, source_id)


# Unauthenticated -- GitHub redirects the user's browser here directly with
# ?code&state, before any Helix session context exists for this request.
# The `state` param (encrypted, short-TTL) is the entire credential,
# mirroring workflows/router.py's webhook-secret-as-credential pattern.
oauth_router = APIRouter(prefix="/oauth", tags=["connectors"])


@oauth_router.get("/github/callback")
async def github_callback(
    code: str, state: str, db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    source = await service.complete_github_oauth(db, code, state)
    frontend_url = get_settings().frontend_url
    return RedirectResponse(url=f"{frontend_url}/orgs/{source.org_id}/connectors")
