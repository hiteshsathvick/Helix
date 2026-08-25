from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
