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


async def enqueue_agent_run(run_id: uuid.UUID, org_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """SPEC.md §22 puts agent execution on its own queue, separate from
    ingestion — a tool-calling loop can take many seconds (multiple LLM
    round trips plus tool calls), too long to run inline in the request
    that triggers it.
    """
    settings = get_settings()
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        await pool.enqueue_job("run_agent_task", str(run_id), str(org_id), str(agent_id))
    finally:
        await pool.aclose()
