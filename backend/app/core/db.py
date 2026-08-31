from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.tracing import instrument_sqlalchemy_engine


class Base(DeclarativeBase):
    """Shared declarative base. Domain modules define their models against this
    so Alembic autogenerate has one metadata object to diff against."""


# NullPool: asyncpg connections are bound to the event loop that first used
# them, and pytest-asyncio may run tests on different loops. Pooling would
# reuse a connection across loops and crash. Revisit connection pooling as
# part of Phase 23 (Performance & Scalability) once there's a stable
# single-loop production profile to tune against.
engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
session_factory = async_sessionmaker(engine, expire_on_commit=False)
# Every DB query becomes a span (SPEC.md §30 "API -> worker -> LLM" trace)
# regardless of whether configure_tracing() has run yet in this process --
# instrumentation just attaches to the engine's event hooks; spans go
# through whatever TracerProvider is current when each query actually runs.
instrument_sqlalchemy_engine(engine)
