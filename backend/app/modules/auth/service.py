import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)
from app.modules.auth.models import RefreshToken, User

logger = logging.getLogger("helix.auth")


async def register_user(db: AsyncSession, email: str, password: str) -> User:
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("an account with this email already exists")

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("user registered: %s", user.id)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if (
        user is None
        or user.password_hash is None
        or not verify_password(password, user.password_hash)
    ):
        logger.info("login failed for email: %s", email)
        raise UnauthorizedError("invalid email or password")

    if not user.is_active:
        logger.info("login failed (inactive user): %s", user.id)
        raise UnauthorizedError("invalid email or password")

    logger.info("login succeeded: %s", user.id)
    return user


async def get_users_by_ids(
    db: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, User]:
    """Public lookup other modules use instead of importing/querying User
    directly — e.g. orgs needs member emails without reaching into auth's
    table (CLAUDE.md §3: cross-module access goes through service interfaces)."""
    if not user_ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(user_ids)))
    return {user.id: user for user in result.scalars().all()}


async def set_active_org(db: AsyncSession, user: User, org_id: uuid.UUID) -> None:
    user.active_org_id = org_id
    await db.commit()


async def issue_refresh_token(db: AsyncSession, user_id: uuid.UUID) -> str:
    settings = get_settings()
    raw_token = generate_opaque_token()
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_opaque_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_ttl_days),
        )
    )
    await db.commit()
    return raw_token


async def rotate_refresh_token(db: AsyncSession, raw_token: str) -> tuple[User, str]:
    """Validate + revoke the given refresh token and issue a new one.

    Raises UnauthorizedError if the token is missing, expired, or already
    revoked — reuse of an already-rotated token is a theft signal, not
    silently tolerated (SPEC.md §13: refresh tokens are rotating).
    """
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_opaque_token(raw_token))
    )
    record = result.scalar_one_or_none()

    now = datetime.now(UTC)
    if record is None or record.revoked_at is not None or record.expires_at < now:
        raise UnauthorizedError("refresh token is invalid or expired")

    record.revoked_at = now

    user = await db.get(User, record.user_id)
    if user is None or not user.is_active:
        await db.commit()
        raise UnauthorizedError("refresh token is invalid or expired")

    new_raw_token = await issue_refresh_token(db, user.id)
    logger.info("refresh token rotated: %s", user.id)
    return user, new_raw_token


async def revoke_refresh_token(db: AsyncSession, raw_token: str) -> User | None:
    """Returns the affected user (for the router to audit the logout
    against their active org), or None if the token was already
    revoked/unknown -- a logout with no session to revoke isn't audited."""
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_opaque_token(raw_token))
    )
    record = result.scalar_one_or_none()
    if record is None or record.revoked_at is not None:
        return None

    record.revoked_at = datetime.now(UTC)
    await db.commit()
    logger.info("refresh token revoked: %s", record.user_id)
    return await db.get(User, record.user_id)
