from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_db
from app.core.errors import UnauthorizedError
from app.core.rate_limit import enforce_rate_limit
from app.core.security import create_access_token
from app.modules.auth import service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import AccessTokenResponse, LoginRequest, RegisterRequest, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_NAME = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=settings.jwt_refresh_token_ttl_days * 24 * 60 * 60,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE_NAME, path=_REFRESH_COOKIE_PATH)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> User:
    return await service.register_user(db, body.email, body.password)


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    await enforce_rate_limit(request, bucket="login")
    user = await service.authenticate_user(db, body.email, body.password)
    refresh_token = await service.issue_refresh_token(db, user.id)
    _set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(
        access_token=create_access_token(user.id), user=UserRead.model_validate(user)
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> AccessTokenResponse:
    raw_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if raw_token is None:
        raise UnauthorizedError("missing refresh token")

    user, new_raw_token = await service.rotate_refresh_token(db, raw_token)
    _set_refresh_cookie(response, new_raw_token)
    return AccessTokenResponse(
        access_token=create_access_token(user.id), user=UserRead.model_validate(user)
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    raw_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if raw_token is not None:
        await service.revoke_refresh_token(db, raw_token)
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserRead)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
