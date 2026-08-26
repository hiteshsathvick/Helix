import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import TenantScopedMixin, TimestampMixin, UUIDPKMixin

# Fixed at schema-creation time (the pgvector column dimension is DDL, not a
# runtime setting) — must match the actual output size of whichever model
# core.config.Settings.embedding_model_name names. See app/modules/ingestion/
# embeddings.py, which validates the model's real output against this.
EMBEDDING_DIMENSIONS = 384


class Chunk(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), default=None
    )
    # Generated column: always in sync with `content`, no service-layer
    # bookkeeping needed to keep FTS current.
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )
    # Hash of the document's current DocumentACL rows at ingestion time —
    # lets Phase 8's search filter chunks by ACL without joining
    # document_acls on every query.
    acl_hash: Mapped[str] = mapped_column(String(64))


class Job(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    """DLQ-visible record of one ingestion attempt (SPEC.md §22) — separate
    from Arq's own internal Redis job state, which isn't queryable from our
    DB or visible once a job completes/expires there."""

    __tablename__ = "jobs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), default="ingest_document")
    status: Mapped[str] = mapped_column(String(50), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
