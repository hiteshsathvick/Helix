import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.db import session_factory
from app.core.tenancy import set_tenant_context
from app.modules.agents.models import AgentRun
from app.modules.agents.service import execute_run

logger = logging.getLogger("helix.agents")


async def run_agent_task(ctx: dict[str, Any], run_id: str, org_id: str, agent_id: str) -> None:
    """Registered with Arq as WorkerSettings.functions (app/workers/run.py)
    with max_tries=settings.agent_max_job_attempts (1, by default) —
    unlike ingestion's retryable pipeline, a partially-completed run may
    already have taken real-world action through the http_request/notify
    tools, so this deliberately does not auto-retry a failed attempt; a
    failed run stays "failed" with its error recorded, and the trace
    (agent_steps) shows exactly how far it got.
    """
    run_uuid, org_uuid = uuid.UUID(run_id), uuid.UUID(org_id)

    try:
        async with session_factory() as db:
            await execute_run(db, org_uuid, run_uuid)
    except Exception:
        logger.exception("agent run %s crashed outside execute_run's own error handling", run_id)
        async with session_factory() as db:
            await set_tenant_context(db, org_uuid)
            run = await db.get(AgentRun, run_uuid)
            if run is not None and run.status != "completed":
                run.status = "failed"
                run.error = "worker crashed while executing this run"
                run.finished_at = datetime.now(UTC)
                await db.commit()
        raise
