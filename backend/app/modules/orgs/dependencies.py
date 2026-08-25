import uuid

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import NotFoundError
from app.core.tenancy import set_tenant_context
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.orgs.models import Membership


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
