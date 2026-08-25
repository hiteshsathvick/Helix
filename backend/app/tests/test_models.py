import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db import session_factory
from app.core.tenancy import set_tenant_context
from app.modules.auth.models import User
from app.modules.orgs.models import Membership, Organization
from app.modules.orgs.system_roles import MEMBER_ROLE_ID


@pytest.mark.asyncio
async def test_user_timestamps_and_soft_delete_default() -> None:
    async with session_factory() as session:
        user = User(email=f"user-{uuid.uuid4()}@example.com")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        assert user.created_at is not None
        assert user.updated_at is not None
        assert user.deleted_at is None
        assert user.is_active is True
        assert user.password_hash is None


@pytest.mark.asyncio
async def test_membership_unique_org_user_constraint() -> None:
    async with session_factory() as session:
        org = Organization(name="Dup Test", slug=f"dup-test-{uuid.uuid4()}")
        user = User(email=f"dup-test-{uuid.uuid4()}@example.com")
        session.add_all([org, user])
        await session.flush()

        await set_tenant_context(session, org.id)
        session.add(Membership(org_id=org.id, user_id=user.id, role_id=MEMBER_ROLE_ID))
        await session.flush()

        session.add(Membership(org_id=org.id, user_id=user.id, role_id=MEMBER_ROLE_ID))
        with pytest.raises(IntegrityError):
            await session.flush()
