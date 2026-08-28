import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.rate_limit import enforce_api_key_rate_limit
from app.core.tenancy import set_tenant_context
from app.modules.api import service as api_service

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ApiKeyPrincipal:
    org_id: uuid.UUID
    # created_by_user_id -- ACL-aware operations (search) act with this
    # user's visibility. See ApiKey's model docstring.
    user_id: uuid.UUID
    key_id: uuid.UUID


def require_api_key(scope: str) -> Callable[..., Coroutine[Any, Any, ApiKeyPrincipal]]:
    """Dependency factory for the public API router, parallel to
    orgs/dependencies.py::require_permission but for key-scoped access
    instead of session-based RBAC -- deliberately not unified with it (see
    Phase 18's plan): the public API is a small, separate subset, not a
    retrofit of every existing endpoint.
    """

    async def _check(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
        db: AsyncSession = Depends(get_db),
    ) -> ApiKeyPrincipal:
        if credentials is None:
            raise UnauthorizedError("missing bearer token")
        key = await api_service.resolve_api_key(db, credentials.credentials)
        if key is None:
            raise UnauthorizedError("invalid or revoked api key")
        if scope not in key.scopes:
            raise ForbiddenError(f"api key missing required scope: {scope}")
        await enforce_api_key_rate_limit(str(key.id))
        # resolve_api_key deliberately doesn't set this (see its docstring
        # -- it runs before any org is known) -- every downstream service
        # call this principal feeds into (search, documents, ...) is
        # RLS-protected and needs it, the same role require_org_member
        # plays for the session-based path.
        await set_tenant_context(db, key.org_id)
        return ApiKeyPrincipal(org_id=key.org_id, user_id=key.created_by_user_id, key_id=key.id)

    return _check
