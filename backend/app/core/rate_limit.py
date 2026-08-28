from fastapi import Request

from app.core.config import get_settings
from app.core.errors import RateLimitedError
from app.core.redis import get_redis_client


async def _enforce_fixed_window(
    identifier: str, *, bucket: str, max_count: int, window_seconds: int
) -> None:
    """Fixed-window counter shared by every rate-limited surface -- only
    what "identifies the caller" and the budget/window differ between
    them (client IP for auth endpoints, API key id for the public API)."""
    key = f"ratelimit:{bucket}:{identifier}"

    client = get_redis_client()
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
    finally:
        await client.aclose()

    if count > max_count:
        raise RateLimitedError("too many attempts, try again later")


async def enforce_rate_limit(request: Request, *, bucket: str) -> None:
    """Per client IP. Raises RateLimitedError (429) once the window's
    attempt budget is exhausted."""
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    await _enforce_fixed_window(
        client_ip,
        bucket=bucket,
        max_count=settings.auth_rate_limit_max_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )


async def enforce_api_key_rate_limit(api_key_id: str) -> None:
    """Per API key (SPEC.md §18), independent of and in addition to any
    per-org quota -- a single misbehaving integration shouldn't be able to
    starve the org's other keys."""
    settings = get_settings()
    await _enforce_fixed_window(
        api_key_id,
        bucket="public_api",
        max_count=settings.public_api_rate_limit_max_requests,
        window_seconds=settings.public_api_rate_limit_window_seconds,
    )
