import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.modules.auth.models import User

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("missing bearer token")

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("invalid or expired token") from exc

    user_id = payload.get("sub")
    user = await db.get(User, uuid.UUID(user_id)) if user_id else None
    if user is None or not user.is_active:
        raise UnauthorizedError("invalid or expired token")

    return user
