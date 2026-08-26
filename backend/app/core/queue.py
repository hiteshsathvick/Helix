import uuid

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings


async def enqueue_ingestion_job(
    job_id: uuid.UUID, org_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    # A fresh pool per call, not a shared one: same event-loop-binding
    # reason as core.redis.get_redis_client (Phase 3) — pytest-asyncio can
    # run different tests/calls on different loops.
    settings = get_settings()
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        await pool.enqueue_job("ingest_document_task", str(job_id), str(org_id), str(document_id))
    finally:
        await pool.aclose()
