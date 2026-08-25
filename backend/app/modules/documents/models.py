import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import SoftDeleteMixin, TenantScopedMixin, TimestampMixin, UUIDPKMixin


class Source(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, TenantScopedMixin, Base):
    """Phase 6 only ever creates "manual" sources (see
    documents.service.get_or_create_manual_source) — real connectors land in
    Phase 14, which will add other `type` values."""

    __tablename__ = "sources"

    type: Mapped[str] = mapped_column(String(50), default="manual")
    name: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="active")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Document(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, TenantScopedMixin, Base):
    __tablename__ = "documents"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(1024))
    # "pending" until Phase 7's ingestion pipeline actually processes it —
    # Phase 6 only proves upload/store/list/delete, not extraction.
    status: Mapped[str] = mapped_column(String(50), default="pending")
    checksum: Mapped[str] = mapped_column(String(64))
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)


class DocumentACL(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    """`principal_type` is "org" for every Phase 6 row (default org-wide
    visibility on upload); "user"/"role" principal types are structurally
    supported for when connectors (Phase 14) or per-user sharing map
    finer-grained permissions onto documents."""

    __tablename__ = "document_acls"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(50))
    principal_id: Mapped[uuid.UUID] = mapped_column()
