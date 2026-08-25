import secrets
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_ttl_minutes),
    }
    if org_id is not None:
        payload["org_id"] = str(org_id)
    key = settings.jwt_signing_keys[settings.jwt_active_kid]
    return jwt.encode(payload, key, algorithm="HS256", headers={"kid": settings.jwt_active_kid})


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError (or a subclass) on any invalid/expired token."""
    settings = get_settings()
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    key = settings.jwt_signing_keys.get(kid) if kid else None
    if key is None:
        raise jwt.InvalidKeyError(f"unknown signing key id: {kid!r}")
    return jwt.decode(token, key, algorithms=["HS256"])


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_opaque_token(token: str) -> str:
    # SHA-256, not Argon2: this hashes high-entropy random tokens (refresh
    # tokens, invitation tokens), not user-chosen passwords, and the check
    # happens on every use — a fast, deterministic hash is appropriate here,
    # unlike passwords where slow hashing is the point.
    return sha256(token.encode()).hexdigest()
