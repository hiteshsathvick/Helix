import logging
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.queue import enqueue_connector_sync
from app.modules.connectors import service as connectors_service
from app.modules.documents import service as documents_service
from app.modules.orgs import service as orgs_service

logger = logging.getLogger("helix.connectors")


async def sync_connector_task(ctx: dict[str, Any], source_id: str, org_id: str) -> None:
    """Registered with Arq (app/workers/run.py),
    max_tries=settings.connector_sync_max_job_attempts. Retry is Arq's own
    re-invocation, same as ingestion's ingest_document_task -- run_sync
    itself already marks the Source "error" with last_sync_error on the
    final attempt's failure, mirroring that task's DLQ-visibility pattern
    but scoped to Source rather than a separate Job row (see the Phase 14
    plan's §2 for why)."""
    source_uuid, org_uuid = uuid.UUID(source_id), uuid.UUID(org_id)
    async with session_factory() as db:
        await connectors_service.run_sync(db, org_uuid, source_uuid)


async def sweep_connector_syncs_task(ctx: dict[str, Any]) -> None:
    """The arq cron entry (WorkerSettings.cron_jobs) driving Phase 14's
    "connectors run incremental syncs on a schedule" (SPEC.md §26) -- a
    fixed, platform-wide sweep, not a per-workflow dynamic schedule (which
    Phase 13 deliberately deferred). Iterates every org (no RLS on
    `organizations` itself) and enqueues one sync per active connector
    source found.
    """
    settings = get_settings()
    enqueued = 0
    async with session_factory() as db:
        org_ids = await orgs_service.list_all_org_ids(db)
        for org_id in org_ids:
            sources = await documents_service.list_connector_sources(db, org_id)
            for source in sources:
                if source.status == "syncing":
                    continue  # already in flight, don't pile on
                await enqueue_connector_sync(source.id, org_id)
                enqueued += 1
    logger.info(
        "connector sync sweep: %s source(s) enqueued across %s org(s), interval=%sm",
        enqueued,
        len(org_ids),
        settings.connector_sync_interval_minutes,
    )
