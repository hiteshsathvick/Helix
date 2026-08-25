import uuid
from typing import Any

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.core.tenancy import set_current_user_context
from app.modules.auth.models import User

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    if credentials is None:
        raise UnauthorizedError("missing bearer token")
    try:
        return decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("invalid or expired token") from exc


async def get_current_user(
    payload: dict[str, Any] = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> User:
    user_id = payload.get("sub")
    user = await db.get(User, uuid.UUID(user_id)) if user_id else None
    if user is None or not user.is_active:
        raise UnauthorizedError("invalid or expired token")

    # Every authenticated request can see its own rows across all orgs (e.g.
    # "list the orgs I belong to"), independent of any single org a specific
    # endpoint later scopes the session to via set_tenant_context.
    await set_current_user_context(db, user.id)

    return user
