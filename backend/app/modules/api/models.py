import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import TenantScopedMixin, TimestampMixin, UUIDPKMixin


class ApiKey(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    """Scoped credential for the public API (SPEC.md §12/§18). The raw key
    is shown to the caller exactly once at creation and never stored --
    `hash` is a SHA-256 of it (same fast-hash-for-high-entropy-random-value
    reasoning as refresh/invitation tokens, core/security.py). `prefix` is
    the first 12 chars of the raw key, kept in the clear purely so a caller
    can recognize which key is which in a list without ever re-seeing the
    secret.

    `created_by_user_id`, not in SPEC.md §10's rough schema sketch: search
    (and any future ACL-aware operation) needs *someone's* permission set
    to filter by (SPEC.md §18 "ACL-aware retrieval" doesn't stop applying
    just because the caller is a key instead of a logged-in session) -- the
    key acts with its creator's visibility, the same way a personal access
    token does on GitHub.

    Deliberately **not** RLS-protected, unlike Webhook/WebhookDelivery below
    -- the public API resolves a key by its hash before any org context is
    known (the same chicken-and-egg problem orgs/models.py's Invitation
    solves the same way: "the random, single-use token itself is the
    authorization"). Every service function still explicitly filters by
    org_id for management operations; only the initial hash lookup runs
    unscoped.
    """

    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(20), index=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Webhook(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    """Outbound subscription (SPEC.md §18). `secret` signs every delivery
    (api/tasks.py::deliver_webhook_task) -- shown once at creation like an
    API key's raw value, never re-displayed."""

    __tablename__ = "webhooks"

    url: Mapped[str] = mapped_column(String(2048))
    secret: Mapped[str] = mapped_column(String(255))
    events: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)


class WebhookDelivery(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    """One row per (webhook, event) delivery attempt sequence -- the log
    that makes "webhooks deliver reliably" (SPEC.md §18 DoD) something an
    admin can actually verify, same role notifications' own status column
    plays for email. Not append-only like audit_logs: this row's status/
    attempts/error are updated in place across retries of the *same*
    delivery, one row per originating event, not one row per HTTP attempt.
    """

    __tablename__ = "webhook_deliveries"

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhooks.id"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domain_events.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100))
    # "pending" -> "delivered" | "failed"
    status: Mapped[str] = mapped_column(String(20), default="pending")
    response_status: Mapped[int | None] = mapped_column(Integer, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
