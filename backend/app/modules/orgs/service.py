import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, QuotaExceededError
from app.core.security import generate_opaque_token, hash_opaque_token
from app.core.tenancy import set_tenant_context
from app.modules.audit import service as audit_service
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.billing.plans import get_plan
from app.modules.orgs.models import Invitation, Membership, Organization, Role
from app.modules.orgs.schemas import MemberRead
from app.modules.orgs.system_roles import MEMBER_ROLE_ID, OWNER_ROLE_ID

logger = logging.getLogger("helix.orgs")

_INVITATION_TTL_DAYS = 7


async def create_org(db: AsyncSession, creator: User, name: str, slug: str) -> Organization:
    existing = await db.execute(select(Organization).where(Organization.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("an organization with this slug already exists")

    org = Organization(name=name, slug=slug)
    db.add(org)
    await db.flush()

    db.add(Membership(org_id=org.id, user_id=creator.id, role_id=OWNER_ROLE_ID))

    if creator.active_org_id is None:
        creator.active_org_id = org.id

    await db.commit()
    await db.refresh(org)
    logger.info("org created: %s by %s", org.id, creator.id)
    return org


async def get_organization(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    org = await db.get(Organization, org_id)
    if org is None:
        raise NotFoundError("organization not found")
    return org


async def update_org_plan(db: AsyncSession, org_id: uuid.UUID, plan: str) -> None:
    """Called by billing/service.py's webhook handler once a Stripe
    subscription is confirmed -- orgs owns the `Organization` table, so
    billing goes through this rather than importing the model directly
    (CLAUDE.md §3). `Organization.plan` (Phase 6, unused until billing
    existed) is the fast-path field every quota/cap check reads.
    """
    await db.execute(update(Organization).where(Organization.id == org_id).values(plan=plan))
    await db.commit()


async def list_all_org_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Every non-deleted org, for a platform-wide periodic sweep (Phase 14's
    connector sync cron, see connectors/tasks.py) rather than a per-org
    request. `organizations` carries no org_id of its own to scope by and
    has no RLS policy (Role's docstring notes the same for a similar
    reason) -- no set_tenant_context call needed here."""
    result = await db.execute(select(Organization.id).where(Organization.deleted_at.is_(None)))
    return list(result.scalars().all())


async def get_org_settings(db: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    """Public read of `organizations.settings` for other modules (e.g. `ai`
    resolving per-org model config) — CLAUDE.md §3: cross-module access goes
    through a service function, never a direct query against another
    module's table."""
    org = await get_organization(db, org_id)
    return org.settings


async def update_org_settings(
    db: AsyncSession, org_id: uuid.UUID, patch: dict[str, Any]
) -> dict[str, Any]:
    """Shallow-merges `patch` into `organizations.settings` and persists it.
    Callers (e.g. `ai.service.update_org_ai_config`) own validating which
    keys/values are meaningful — this just owns the JSONB column."""
    org = await get_organization(db, org_id)
    org.settings = {**org.settings, **patch}
    await db.commit()
    return org.settings


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

    role_ids = [m.role_id for m in memberships]
    roles_result = await db.execute(select(Role).where(Role.id.in_(role_ids)))
    roles_by_id = {role.id: role for role in roles_result.scalars().all()}

    return [
        MemberRead(
            id=m.id,
            user_id=m.user_id,
            email=users_by_id[m.user_id].email if m.user_id in users_by_id else "unknown",
            status=m.status,
            role_name=roles_by_id[m.role_id].name if m.role_id in roles_by_id else "unknown",
            created_at=m.created_at,
        )
        for m in memberships
    ]


async def create_invitation(
    db: AsyncSession, org_id: uuid.UUID, invited_by: User, email: str
) -> tuple[Invitation, str]:
    # Seat quota (SPEC.md §16). Counts pending invitations too, not just
    # active members -- otherwise a 3-seat plan could issue an unbounded
    # number of outstanding invites, all racing to accept past the limit.
    # `billing.plans` is pure config (no models) -- importing it here isn't
    # the cross-module table access CLAUDE.md §3 forbids.
    org = await get_organization(db, org_id)
    seats_limit = get_plan(org.plan).seats_limit
    if seats_limit is not None:
        member_count = len(await list_org_members(db, org_id))
        pending_result = await db.execute(
            select(func.count())
            .select_from(Invitation)
            .where(
                Invitation.org_id == org_id,
                Invitation.status == "pending",
                Invitation.expires_at >= datetime.now(UTC),
            )
        )
        seats_used = member_count + pending_result.scalar_one()
        if seats_used >= seats_limit:
            raise QuotaExceededError(
                "organization has reached its plan's seat limit",
                details={"plan": org.plan, "seats_limit": seats_limit, "seats_used": seats_used},
            )

    raw_token = generate_opaque_token()
    invitation = Invitation(
        org_id=org_id,
        email=email,
        token_hash=hash_opaque_token(raw_token),
        invited_by_user_id=invited_by.id,
        expires_at=datetime.now(UTC) + timedelta(days=_INVITATION_TTL_DAYS),
    )
    db.add(invitation)
    await audit_service.record(
        db,
        org_id,
        invited_by.id,
        "invitation.created",
        resource_type="invitation",
        resource_id=invitation.id,
        metadata={"email": email},
    )
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

    # The accepting user has no membership in this org yet, so no tenant
    # context was ever established for it in this session -- set it now
    # (matches the org they're about to join) so the audit insert below
    # satisfies audit_logs' plain "org_id = current_org" RLS check. The
    # membership insert just below already worked without this (its own
    # policy has a separate user_id branch, per the comment there), but
    # setting it explicitly is correct regardless and costs nothing.
    await set_tenant_context(db, invitation.org_id)

    existing_membership = await db.execute(
        select(Membership.id).where(
            Membership.org_id == invitation.org_id, Membership.user_id == accepting_user.id
        )
    )
    if existing_membership.scalar_one_or_none() is None:
        # Relies on the user_id branch of the memberships RLS policy — the
        # accepting user has no membership (and thus no tenant context) for
        # this org yet, but their own new row always satisfies WITH CHECK.
        db.add(
            Membership(org_id=invitation.org_id, user_id=accepting_user.id, role_id=MEMBER_ROLE_ID)
        )

    invitation.status = "accepted"
    invitation.accepted_by_user_id = accepting_user.id

    if accepting_user.active_org_id is None:
        accepting_user.active_org_id = invitation.org_id

    await audit_service.record(
        db,
        invitation.org_id,
        accepting_user.id,
        "invitation.accepted",
        resource_type="invitation",
        resource_id=invitation.id,
    )
    await db.commit()
    await db.refresh(org)
    logger.info("invitation accepted: %s by %s", invitation.id, accepting_user.id)
    return org


async def get_membership_role(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> Role | None:
    result = await db.execute(
        select(Role)
        .join(Membership, Membership.role_id == Role.id)
        .where(Membership.org_id == org_id, Membership.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_org_roles(db: AsyncSession, org_id: uuid.UUID) -> list[Role]:
    # Not RLS-scoped (Role has none) — filtered explicitly here instead:
    # system roles (org_id IS NULL) plus this org's own custom roles.
    result = await db.execute(select(Role).where((Role.org_id.is_(None)) | (Role.org_id == org_id)))
    return list(result.scalars().all())


async def create_custom_role(
    db: AsyncSession, org_id: uuid.UUID, name: str, permissions: list[str]
) -> Role:
    role = Role(org_id=org_id, name=name, permissions=permissions)
    db.add(role)
    await db.commit()
    await db.refresh(role)
    logger.info("custom role created for org %s: %s", org_id, role.id)
    return role


async def update_membership_role(
    db: AsyncSession,
    org_id: uuid.UUID,
    membership_id: uuid.UUID,
    role_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> MemberRead:
    role = await db.get(Role, role_id)
    if role is None or (role.org_id is not None and role.org_id != org_id):
        raise NotFoundError("role not found")

    result = await db.execute(
        select(Membership).where(Membership.id == membership_id, Membership.org_id == org_id)
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise NotFoundError("member not found")

    membership.role_id = role_id
    await audit_service.record(
        db,
        org_id,
        actor_id,
        "member.role_updated",
        resource_type="membership",
        resource_id=membership.id,
        metadata={"role_id": str(role_id)},
    )
    await db.commit()
    logger.info("membership %s role changed to %s in org %s", membership_id, role_id, org_id)

    # Build the response from data already in hand rather than re-querying
    # memberships: `db.commit()` just ended the transaction, and with it the
    # SET LOCAL/set_config tenant context RLS needs — a fresh
    # membership-table query here would come back empty until that's
    # re-established. Looking up the user's email is fine post-commit since
    # `users` carries no RLS policy.
    users_by_id = await auth_service.get_users_by_ids(db, [membership.user_id])
    return MemberRead(
        id=membership.id,
        user_id=membership.user_id,
        email=users_by_id[membership.user_id].email
        if membership.user_id in users_by_id
        else "unknown",
        status=membership.status,
        role_name=role.name,
        created_at=membership.created_at,
    )
