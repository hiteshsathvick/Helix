import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import TenantScopedMixin, TimestampMixin, UUIDPKMixin


class Notification(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # "email" | "in_app"
    channel: Mapped[str] = mapped_column(String(20))
    # Matches NotificationPref.event -- the join key between a fired
    # notification and the preference that governed it.
    event_type: Mapped[str] = mapped_column(String(100))
    # Which templates/registry.py entry rendered this row, for traceability.
    template: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    subject: Mapped[str | None] = mapped_column(String(500), default=None)  # email only
    # Rendered once at creation time, not re-rendered at send -- a later
    # template edit never changes the text of an already-created,
    # still-queued notification, and in-app reads render straight from the
    # row with no template lookup.
    body: Mapped[str] = mapped_column(Text)
    # "pending" (immediate, not yet attempted) -> "sent" | "failed"
    # "queued_for_digest" (email + digest-frequency pref only) -> "sent"
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    # NULL = unread. The in-app inbox's read/unread signal.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        Index("ix_notifications_org_user_created", "org_id", "user_id", "created_at", "id"),
    )


class NotificationPref(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20))
    event: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # "immediate" | "digest" -- meaningful for channel="email" only; the
    # in-app channel always delivers immediately regardless (see
    # notifications/service.py::notify's docstring for why).
    frequency: Mapped[str] = mapped_column(String(20), default="immediate")

    __table_args__ = (UniqueConstraint("org_id", "user_id", "channel", "event"),)
