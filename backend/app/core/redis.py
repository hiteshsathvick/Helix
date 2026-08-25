from redis import asyncio as redis_asyncio

from app.core.config import get_settings


def get_redis_client() -> redis_asyncio.Redis:
    # A fresh client per call, not a shared pooled singleton: redis-py's
    # async connections bind to the event loop that first used them, and
    # pytest-asyncio can run different tests on different loops — same class
    # of issue as the NullPool decision in core/db.py. Revisit alongside
    # Postgres connection pooling in Phase 23 (Performance & Scalability).
    return redis_asyncio.from_url(get_settings().redis_url, decode_responses=True)
