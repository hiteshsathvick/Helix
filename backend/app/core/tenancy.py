import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant_context(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Scope the current transaction to one org for Postgres RLS.

    Must be called within a transaction (set_config's is_local=true makes it
    transaction-scoped, like SET LOCAL) and before any tenant-scoped query on
    that session. Uses set_config() rather than `SET LOCAL ... = :param`
    because Postgres does not accept bind parameters as a SET value.
    """
    await session.execute(
        text("SELECT set_config('app.current_org', :org_id, true)"), {"org_id": str(org_id)}
    )
