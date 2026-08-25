import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import ForbiddenError, NotFoundError
from app.core.tenancy import set_tenant_context
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.orgs.models import Membership, Role

logger = logging.getLogger("helix.orgs")


async def require_org_member(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Path-scoped authorization + RLS context for any `/orgs/{org_id}/...`
    endpoint. Re-verifies membership against the DB on every call rather
    than trusting a JWT claim, since membership can be revoked mid-session.
    404 (not 403) on failure so a non-member can't distinguish 'org exists
    but you're not in it' from 'org doesn't exist'.
    """
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Membership.id).where(
            Membership.org_id == org_id, Membership.user_id == current_user.id
        )
    )
    if result.scalar_one_or_none() is None:
        raise NotFoundError("organization not found")
    return org_id


def require_permission(
    permission: str,
) -> Callable[..., Coroutine[Any, Any, uuid.UUID]]:
    """Dependency factory: `Depends(require_permission("members:invite"))`.

    Composes with require_org_member (membership + RLS context already
    verified), then resolves the caller's role for that org and checks the
    permission is in its list — SPEC.md §14: checked after authentication
    and tenant resolution, before business logic. Denials are logged
    (SPEC.md §14 "denials are audited"); persisted audit_logs is Phase 17.
    """

    async def _check(
        org_id: uuid.UUID = Depends(require_org_member),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> uuid.UUID:
        result = await db.execute(
            select(Role.permissions)
            .join(Membership, Membership.role_id == Role.id)
            .where(Membership.org_id == org_id, Membership.user_id == current_user.id)
        )
        permissions = result.scalar_one_or_none() or []
        if permission not in permissions:
            logger.warning(
                "permission denied: user=%s org=%s permission=%s",
                current_user.id,
                org_id,
                permission,
            )
            raise ForbiddenError(f"missing required permission: {permission}")
        return org_id

    return _check
