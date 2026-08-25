import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import SoftDeleteMixin, TenantScopedMixin, TimestampMixin, UUIDPKMixin


class Role(UUIDPKMixin, TimestampMixin, Base):
    """org_id is nullable, unlike TenantScopedMixin's non-null FK: system
    roles (Owner/Admin/Member/Viewer) are global (org_id NULL) and must stay
    visible to every org; org-specific custom roles set it. No RLS here —
    permission names aren't sensitive data, and "NULL or mine" visibility is
    simpler to get right as an explicit query filter than as a policy."""

    __tablename__ = "roles"

    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), default=None)
    name: Mapped[str] = mapped_column(String(100))
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)


class Organization(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(50), default="free")
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)


class Membership(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, TenantScopedMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), nullable=False)


class Invitation(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, TenantScopedMixin, Base):
    """Deliberately NOT RLS-protected, unlike Membership: the whole point of
    an invitation is to grant access to someone who isn't a member of org_id
    yet, so org-scoped RLS would be backwards here. The random, single-use
    token itself is the authorization — same bearer-token pattern as
    RefreshToken, which is also unprotected by RLS for the same reason."""

    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(320), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), default=None
    )
