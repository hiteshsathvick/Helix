import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import SoftDeleteMixin, TenantScopedMixin, TimestampMixin, UUIDPKMixin


class Source(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, TenantScopedMixin, Base):
    """Phase 6 only ever created "manual" sources (see
    documents.service.get_or_create_manual_source); Phase 14's connectors
    module adds "web"/"github" (see app/modules/connectors), storing
    connector-specific state (URL lists, encrypted OAuth tokens, sync
    cursors) in `config` — connectors never gets its own ORM model, it
    operates entirely on Source/Document/DocumentACL through this module's
    public service interface (CLAUDE.md §3)."""

    __tablename__ = "sources"

    type: Mapped[str] = mapped_column(String(50), default="manual")
    name: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="active")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Set by a connector sync that failed after exhausting its retries
    # (SPEC.md §22-adjacent visibility, scoped to Source rather than a
    # separate DLQ table for v1 — see connectors/tasks.py).
    last_sync_error: Mapped[str | None] = mapped_column(Text, default=None)


class Document(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, TenantScopedMixin, Base):
    __tablename__ = "documents"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    # Null for manual uploads (Phase 6). Set by connectors (Phase 14) to the
    # source system's stable item id (a URL, or "path/in/repo") — the key
    # an incremental sync dedups against via
    # documents.service.get_document_by_external_id.
    external_id: Mapped[str | None] = mapped_column(String(1024), default=None)
    title: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(1024))
    # "pending" until Phase 7's ingestion pipeline actually processes it —
    # Phase 6 only proves upload/store/list/delete, not extraction.
    status: Mapped[str] = mapped_column(String(50), default="pending")
    checksum: Mapped[str] = mapped_column(String(64))
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (Index("ix_documents_source_id_external_id", "source_id", "external_id"),)


class DocumentACL(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    """`principal_type` is "org" for every Phase 6 row (default org-wide
    visibility on upload); "user"/"role" principal types are structurally
    supported for when connectors (Phase 14) or per-user sharing map
    finer-grained permissions onto documents."""

    __tablename__ = "document_acls"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(50))
    principal_id: Mapped[uuid.UUID] = mapped_column()
