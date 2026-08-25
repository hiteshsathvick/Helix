from fastapi import Request

from app.core.config import get_settings
from app.core.errors import RateLimitedError
from app.core.redis import get_redis_client


async def enforce_rate_limit(request: Request, *, bucket: str) -> None:
    """Fixed-window counter per client IP. Raises RateLimitedError (429) once
    the window's attempt budget is exhausted."""
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    key = f"ratelimit:{bucket}:{client_ip}"

    client = get_redis_client()
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, settings.auth_rate_limit_window_seconds)
    finally:
        await client.aclose()

    if count > settings.auth_rate_limit_max_attempts:
        raise RateLimitedError("too many attempts, try again later")
