import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.security import create_access_token
from app.modules.auth import service as auth_service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import AccessTokenResponse, UserRead
from app.modules.orgs import service
from app.modules.orgs.dependencies import require_org_member
from app.modules.orgs.schemas import (
    InvitationCreate,
    InvitationCreatedResponse,
    InvitationRead,
    MemberRead,
    OrgCreate,
    OrgRead,
)

router = APIRouter(prefix="/orgs", tags=["orgs"])
invitations_router = APIRouter(prefix="/invitations", tags=["orgs"])


@router.post("", response_model=OrgRead, status_code=status.HTTP_201_CREATED)
async def create_org(
    body: OrgCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrgRead:
    org = await service.create_org(db, current_user, body.name, body.slug)
    return OrgRead.model_validate(org)


@router.get("", response_model=list[OrgRead])
async def list_my_orgs(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[OrgRead]:
    orgs = await service.list_user_orgs(db, current_user.id)
    return [OrgRead.model_validate(org) for org in orgs]


@router.get("/{org_id}/members", response_model=list[MemberRead])
async def list_members(
    org_id: uuid.UUID = Depends(require_org_member), db: AsyncSession = Depends(get_db)
) -> list[MemberRead]:
    return await service.list_org_members(db, org_id)


@router.post(
    "/{org_id}/invitations",
    response_model=InvitationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    body: InvitationCreate,
    org_id: uuid.UUID = Depends(require_org_member),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvitationCreatedResponse:
    invitation, raw_token = await service.create_invitation(db, org_id, current_user, body.email)
    return InvitationCreatedResponse(
        invitation=InvitationRead.model_validate(invitation), token=raw_token
    )


@router.post("/{org_id}/switch", response_model=AccessTokenResponse)
async def switch_org(
    org_id: uuid.UUID = Depends(require_org_member),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    await auth_service.set_active_org(db, current_user, org_id)
    return AccessTokenResponse(
        access_token=create_access_token(current_user.id, org_id),
        user=UserRead.model_validate(current_user),
    )


@invitations_router.post("/{token}/accept", response_model=AccessTokenResponse)
async def accept_invitation(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    await service.accept_invitation(db, token, current_user)
    return AccessTokenResponse(
        access_token=create_access_token(current_user.id, current_user.active_org_id),
        user=UserRead.model_validate(current_user),
    )
