import logging
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.events import publish_event
from app.core.tenancy import set_tenant_context
from app.modules.documents import service as documents_service
from app.modules.ingestion.models import Job
from app.modules.ingestion.pipeline import run_ingestion

logger = logging.getLogger("helix.ingestion")


async def ingest_document_task(
    ctx: dict[str, Any], job_id: str, org_id: str, document_id: str
) -> None:
    """Registered with Arq as WorkerSettings.functions (see app/workers/run.py),
    with max_tries=settings.ingestion_max_job_attempts. Arq itself drives the
    actual retry/backoff (re-raising below is what triggers it); this
    function's job is keeping the Job row's status/attempts/error in sync
    with each attempt, and marking it "dlq" on the final one — SPEC.md §22
    wants DLQ state visible from our own DB, not just inside Arq's Redis
    state.
    """
    settings = get_settings()
    job_uuid, org_uuid, document_uuid = (
        uuid.UUID(job_id),
        uuid.UUID(org_id),
        uuid.UUID(document_id),
    )
    current_try = ctx.get("job_try", 1)
    is_last_attempt = current_try >= settings.ingestion_max_job_attempts

    async with session_factory() as db:
        await set_tenant_context(db, org_uuid)
        job = await db.get(Job, job_uuid)
        if job is None:
            logger.error("ingestion job not found: %s", job_id)
            return
        job.status = "running"
        job.attempts = current_try
        await db.commit()

    try:
        async with session_factory() as db:
            chunk_count = await run_ingestion(db, org_uuid, document_uuid)
            await documents_service.mark_document_status(db, org_uuid, document_uuid, "indexed")
        logger.info("ingestion succeeded: document=%s chunks=%s", document_id, chunk_count)

        async with session_factory() as db:
            await set_tenant_context(db, org_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                job.status = "succeeded"
                job.error = None
                # Publishes the event this task just made true and enqueues
                # its dispatch to any workflow triggers (app/core/events.py)
                # — SPEC.md §44's own worked example ("trigger = new
                # document ... → step summarize"). Fired here, not from
                # ingestion/service.py (that fires at job *creation*, before
                # ingestion has even run) or pipeline.py (which only knows
                # chunking succeeded, not that the whole task did).
                await publish_event(
                    db,
                    org_uuid,
                    "document.ingested",
                    {"document_id": document_id},
                    correlation_id=job_uuid,
                )
                await db.commit()

    except Exception as exc:
        logger.exception("ingestion attempt %s failed: document=%s", current_try, document_id)
        async with session_factory() as db:
            await set_tenant_context(db, org_uuid)
            job = await db.get(Job, job_uuid)
            if job is not None:
                job.error = str(exc)
                if is_last_attempt:
                    job.status = "dlq"
                    await documents_service.mark_document_status(
                        db, org_uuid, document_uuid, "failed"
                    )
                else:
                    job.status = "pending"
                await db.commit()
        raise
