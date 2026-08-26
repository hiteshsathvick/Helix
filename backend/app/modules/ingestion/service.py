import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue import enqueue_ingestion_job
from app.core.tenancy import set_tenant_context
from app.modules.ingestion.models import Job

logger = logging.getLogger("helix.ingestion")


async def trigger_ingestion(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> Job:
    job = Job(org_id=org_id, document_id=document_id, kind="ingest_document", status="pending")
    db.add(job)
    await db.commit()
    # db.commit() wipes the SET LOCAL/set_config tenant context RLS needs
    # (Phase 5/6 lesson) — Job is RLS-protected, so refresh() needs it reset.
    await set_tenant_context(db, org_id)
    await db.refresh(job)

    await enqueue_ingestion_job(job.id, org_id, document_id)
    logger.info("ingestion job enqueued: %s for document %s", job.id, document_id)
    return job


async def get_latest_job(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> Job | None:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Job)
        .where(Job.org_id == org_id, Job.document_id == document_id)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
