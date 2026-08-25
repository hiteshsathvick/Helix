import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base. Domain modules define their models against this
    so Alembic autogenerate has one metadata object to diff against."""


class SchemaProbe(Base):
    """Phase 1 infra-proof table only — exercises the migration + DB-session
    pipeline before any real domain model exists. Not a domain concept; safe
    to drop once Phase 2's models give Alembic something real to migrate."""

    __tablename__ = "schema_probes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    message: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


engine = create_async_engine(get_settings().database_url)
session_factory = async_sessionmaker(engine, expire_on_commit=False)
