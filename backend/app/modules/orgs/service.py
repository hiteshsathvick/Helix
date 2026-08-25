import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.security import generate_opaque_token, hash_opaque_token
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.orgs.models import Invitation, Membership, Organization
from app.modules.orgs.schemas import MemberRead

logger = logging.getLogger("helix.orgs")

_INVITATION_TTL_DAYS = 7


async def create_org(db: AsyncSession, creator: User, name: str, slug: str) -> Organization:
    existing = await db.execute(select(Organization).where(Organization.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("an organization with this slug already exists")

    org = Organization(name=name, slug=slug)
    db.add(org)
    await db.flush()

    db.add(Membership(org_id=org.id, user_id=creator.id))

    if creator.active_org_id is None:
        creator.active_org_id = org.id

    await db.commit()
    await db.refresh(org)
    logger.info("org created: %s by %s", org.id, creator.id)
    return org


async def list_user_orgs(db: AsyncSession, user_id: uuid.UUID) -> list[Organization]:
    # No set_tenant_context call: this relies purely on the user_id branch of
    # the memberships RLS policy (set by get_current_user for every
    # authenticated request), which is exactly the "see my own rows across
    # every org" case that branch exists for.
    result = await db.execute(
        select(Organization)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == user_id)
    )
    return list(result.scalars().all())


async def list_org_members(db: AsyncSession, org_id: uuid.UUID) -> list[MemberRead]:
    result = await db.execute(select(Membership).where(Membership.org_id == org_id))
    memberships = list(result.scalars().all())
    users_by_id = await auth_service.get_users_by_ids(db, [m.user_id for m in memberships])
    return [
        MemberRead(
            id=m.id,
            user_id=m.user_id,
            email=users_by_id[m.user_id].email if m.user_id in users_by_id else "unknown",
            status=m.status,
            created_at=m.created_at,
        )
        for m in memberships
    ]


async def create_invitation(
    db: AsyncSession, org_id: uuid.UUID, invited_by: User, email: str
) -> tuple[Invitation, str]:
    raw_token = generate_opaque_token()
    invitation = Invitation(
        org_id=org_id,
        email=email,
        token_hash=hash_opaque_token(raw_token),
        invited_by_user_id=invited_by.id,
        expires_at=datetime.now(UTC) + timedelta(days=_INVITATION_TTL_DAYS),
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    logger.info("invitation created for org %s: %s", org_id, invitation.id)
    return invitation, raw_token


async def accept_invitation(db: AsyncSession, raw_token: str, accepting_user: User) -> Organization:
    result = await db.execute(
        select(Invitation).where(Invitation.token_hash == hash_opaque_token(raw_token))
    )
    invitation = result.scalar_one_or_none()

    now = datetime.now(UTC)
    if invitation is None or invitation.status != "pending" or invitation.expires_at < now:
        raise NotFoundError("invitation not found or no longer valid")

    if invitation.email.lower() != accepting_user.email.lower():
        raise ForbiddenError("this invitation was issued to a different email address")

    org = await db.get(Organization, invitation.org_id)
    if org is None:
        raise NotFoundError("invitation not found or no longer valid")

    existing_membership = await db.execute(
        select(Membership.id).where(
            Membership.org_id == invitation.org_id, Membership.user_id == accepting_user.id
        )
    )
    if existing_membership.scalar_one_or_none() is None:
        # Relies on the user_id branch of the memberships RLS policy — the
        # accepting user has no membership (and thus no tenant context) for
        # this org yet, but their own new row always satisfies WITH CHECK.
        db.add(Membership(org_id=invitation.org_id, user_id=accepting_user.id))

    invitation.status = "accepted"
    invitation.accepted_by_user_id = accepting_user.id

    if accepting_user.active_org_id is None:
        accepting_user.active_org_id = invitation.org_id

    await db.commit()
    await db.refresh(org)
    logger.info("invitation accepted: %s by %s", invitation.id, accepting_user.id)
    return org
