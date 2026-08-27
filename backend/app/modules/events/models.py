import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import TenantScopedMixin, TimestampMixin, UUIDPKMixin


class DomainEvent(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    """Append-only record of an internal domain event (SPEC.md §21) — e.g.
    "document.ingested". Published via app/core/events.py::publish_event,
    consumed by workflows/tasks.py::dispatch_domain_event_task as a
    workflow trigger source. This is a lightweight Postgres-backed event
    bus, not Redis streams — SPEC.md §21 offers both as equal options, and
    this reuses infrastructure (Postgres + Arq) already in the codebase
    instead of adding a second new async-infra piece alongside the
    workflow engine itself.
    """

    __tablename__ = "domain_events"

    type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    correlation_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, index=True)
