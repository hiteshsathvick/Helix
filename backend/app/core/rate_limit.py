import uuid

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


async def enforce_rate_limit(
    request: Request, *, bucket: str, max_count: int, window_seconds: int
) -> None:
    """Per client IP. Raises RateLimitedError (429) once the window's
    attempt budget is exhausted. `max_count`/`window_seconds` are passed in
    by the caller (rather than read from settings here) so this one helper
    serves every IP-keyed surface -- auth attempts, inbound workflow
    webhooks -- each with its own budget."""
    client_ip = request.client.host if request.client else "unknown"
    await _enforce_fixed_window(
        client_ip, bucket=bucket, max_count=max_count, window_seconds=window_seconds
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


async def enforce_user_rate_limit(
    user_id: uuid.UUID, *, bucket: str, max_count: int, window_seconds: int
) -> None:
    """Per authenticated user (SPEC.md §29 "rate limits everywhere") --
    independent of the per-IP and per-API-key limiters above. Covers
    cost-bearing authenticated endpoints (assistant queries, agent runs,
    workflow triggers) where the right identity to key on is the caller,
    not their IP or an API key."""
    await _enforce_fixed_window(
        str(user_id), bucket=bucket, max_count=max_count, window_seconds=window_seconds
    )
