import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_factory
from app.core.tenancy import set_tenant_context
from app.modules.auth.models import User
from app.modules.orgs.models import Membership, Organization
from app.modules.orgs.system_roles import MEMBER_ROLE_ID


@pytest.fixture
async def two_orgs_with_memberships():
    async with session_factory() as setup_session:
        org_a = Organization(name="Org A", slug=f"org-a-{uuid.uuid4()}")
        org_b = Organization(name="Org B", slug=f"org-b-{uuid.uuid4()}")
        user_a = User(email=f"user-a-{uuid.uuid4()}@example.com")
        user_b = User(email=f"user-b-{uuid.uuid4()}@example.com")
        setup_session.add_all([org_a, org_b, user_a, user_b])
        await setup_session.flush()

        # Create memberships without RLS blocking the setup itself: the
        # session's role owns the table, so writes made *without* a
        # mismatching current_org still satisfy WITH CHECK once we set the
        # context per insert.
        await set_tenant_context(setup_session, org_a.id)
        membership_a = Membership(org_id=org_a.id, user_id=user_a.id, role_id=MEMBER_ROLE_ID)
        setup_session.add(membership_a)
        await setup_session.flush()

        await set_tenant_context(setup_session, org_b.id)
        membership_b = Membership(org_id=org_b.id, user_id=user_b.id, role_id=MEMBER_ROLE_ID)
        setup_session.add(membership_b)
        await setup_session.flush()

        await setup_session.commit()
        return org_a.id, org_b.id


async def _visible_org_ids(session: AsyncSession) -> set[uuid.UUID]:
    result = await session.execute(select(Membership.org_id))
    return set(result.scalars().all())


@pytest.mark.asyncio
async def test_session_scoped_to_org_a_sees_only_org_a(two_orgs_with_memberships) -> None:
    org_a_id, org_b_id = two_orgs_with_memberships
    async with session_factory() as session:
        await set_tenant_context(session, org_a_id)
        visible = await _visible_org_ids(session)
        assert visible == {org_a_id}
        assert org_b_id not in visible


@pytest.mark.asyncio
async def test_session_scoped_to_org_b_sees_only_org_b(two_orgs_with_memberships) -> None:
    org_a_id, org_b_id = two_orgs_with_memberships
    async with session_factory() as session:
        await set_tenant_context(session, org_b_id)
        visible = await _visible_org_ids(session)
        assert visible == {org_b_id}
        assert org_a_id not in visible


@pytest.mark.asyncio
async def test_no_tenant_context_set_sees_nothing(two_orgs_with_memberships) -> None:
    org_a_id, org_b_id = two_orgs_with_memberships
    async with session_factory() as session:
        visible = await _visible_org_ids(session)
        assert visible == set()
