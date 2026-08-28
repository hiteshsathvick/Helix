import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import TenantScopedMixin, UUIDPKMixin


class AuditLog(UUIDPKMixin, TenantScopedMixin, Base):
    """Append-only (SPEC.md §28) -- no service function here ever updates or
    deletes a row, only inserts. No TimestampMixin: `updated_at` would be a
    lie for a table nothing ever updates, so this carries only `created_at`
    directly, same precedent as billing's UsageEvent.

    `org_id` (from TenantScopedMixin) is NOT NULL like every other tenant
    table -- account-level actions with no org yet (register, a login
    before any org exists) are simply not audited here rather than forcing
    a nullable exception into the one column every RLS policy in this app
    depends on. `actor_id` is nullable instead, for the events that *do*
    have an org but no human actor (a Stripe webhook plan change).
    """

    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), default=None, index=True
    )
    # Dotted category.verb, e.g. "auth.login", "member.role_updated",
    # "billing.checkout_started", "permission.denied".
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), default=None)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    # Named metadata_ / mapped to the "metadata" column -- `metadata` itself
    # is reserved on every SQLAlchemy declarative model (Base.metadata).
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    # Nullable, and always NULL in this phase -- capturing it would need
    # threading the request IP through every instrumented service function
    # across six modules; the column exists (SPEC.md §10) so it can be
    # filled in incrementally later without a migration.
    ip: Mapped[str | None] = mapped_column(String(45), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_audit_logs_org_created", "org_id", "created_at", "id"),)
