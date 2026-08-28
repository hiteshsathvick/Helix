import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import NotFoundError
from app.core.security import create_access_token
from app.modules.auth import service as auth_service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import AccessTokenResponse, UserRead
from app.modules.orgs import service
from app.modules.orgs.dependencies import require_org_member, require_permission
from app.modules.orgs.schemas import (
    InvitationCreate,
    InvitationCreatedResponse,
    InvitationRead,
    MemberRead,
    MembershipRoleUpdate,
    MyPermissions,
    OrgCreate,
    OrgRead,
    RoleCreate,
    RoleRead,
)
from app.modules.orgs.system_roles import (
    PERMISSION_MEMBERS_INVITE,
    PERMISSION_MEMBERS_MANAGE,
    PERMISSION_ROLES_MANAGE,
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
    # Being a member is enough to see the roster — reading membership status
    # doesn't need its own permission, only inviting/managing others does.
    return await service.list_org_members(db, org_id)


@router.post(
    "/{org_id}/invitations",
    response_model=InvitationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    body: InvitationCreate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_MEMBERS_INVITE)),
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


@router.get("/{org_id}/me", response_model=MyPermissions)
async def my_permissions(
    org_id: uuid.UUID = Depends(require_org_member),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyPermissions:
    role = await service.get_membership_role(db, org_id, current_user.id)
    if role is None:
        raise NotFoundError("organization not found")
    return MyPermissions(role=RoleRead.model_validate(role), permissions=role.permissions)


@router.get("/{org_id}/roles", response_model=list[RoleRead])
async def list_roles(
    org_id: uuid.UUID = Depends(require_org_member), db: AsyncSession = Depends(get_db)
) -> list[RoleRead]:
    roles = await service.list_org_roles(db, org_id)
    return [RoleRead.model_validate(role) for role in roles]


@router.post("/{org_id}/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_ROLES_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    role = await service.create_custom_role(db, org_id, body.name, body.permissions)
    return RoleRead.model_validate(role)


@router.put("/{org_id}/memberships/{membership_id}/role", response_model=MemberRead)
async def update_membership_role(
    membership_id: uuid.UUID,
    body: MembershipRoleUpdate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_MEMBERS_MANAGE)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemberRead:
    return await service.update_membership_role(
        db, org_id, membership_id, body.role_id, current_user.id
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
