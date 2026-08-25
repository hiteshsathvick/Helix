import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import SoftDeleteMixin, TimestampMixin, UUIDPKMixin


class User(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(255), default=None)
    # The org a fresh access token gets scoped to on login/refresh — global
    # per user, not per-session/device (Phase 4 scoping call). Updated by the
    # switch-org endpoint. FK references orgs' table by name only, not an
    # imported Organization class — keeps the module boundary intact.
    active_org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), default=None
    )


class RefreshToken(UUIDPKMixin, TimestampMixin, Base):
    """Opaque, rotating refresh tokens. Only the hash is ever stored — see
    core.security.hash_opaque_token. A row with revoked_at set is dead even
    if not yet expired (used on logout and on rotation of the prior token)."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
