import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.tenancy import set_tenant_context
from app.modules.events.models import DomainEvent
from app.modules.workflows.executor import execute_workflow_run
from app.modules.workflows.models import Workflow, WorkflowRun, WorkflowVersion
from app.modules.workflows.schemas import WorkflowGraph
from app.modules.workflows.service import create_run

logger = logging.getLogger("helix.workflows")


async def execute_workflow_run_task(ctx: dict[str, Any], run_id: str, org_id: str) -> None:
    """Registered with Arq (app/workers/run.py), max_tries=
    settings.workflow_run_max_job_attempts. Unlike agents' run task, a
    crash here is expected to retry: execute_workflow_run always re-derives
    its state from persisted StepRun rows, so a fresh attempt safely
    resumes rather than restarting or duplicating work (SPEC.md §20's
    "a crashed worker's run is resumable"). Only once Arq's own retries are
    exhausted does this mark the run failed as a last resort.
    """
    settings = get_settings()
    run_uuid, org_uuid = uuid.UUID(run_id), uuid.UUID(org_id)
    current_try = ctx.get("job_try", 1)
    is_last_attempt = current_try >= settings.workflow_run_max_job_attempts

    try:
        async with session_factory() as db:
            await execute_workflow_run(db, org_uuid, run_uuid)
    except Exception:
        logger.exception("workflow run %s crashed on attempt %s", run_id, current_try)
        if is_last_attempt:
            async with session_factory() as db:
                await set_tenant_context(db, org_uuid)
                run = await db.get(WorkflowRun, run_uuid)
                if run is not None and run.status not in ("completed", "failed", "cancelled"):
                    run.status = "failed"
                    run.error = "worker crashed while executing this run and retries were exhausted"
                    run.finished_at = datetime.now(UTC)
                    await db.commit()
        raise


async def dispatch_domain_event_task(ctx: dict[str, Any], event_id: str, org_id: str) -> None:
    """Fan-out from one DomainEvent to every active workflow whose current
    version has a trigger node matching its type -- see app/core/events.py's
    publish_event, which enqueues this immediately after committing the
    event row.
    """
    event_uuid, org_uuid = uuid.UUID(event_id), uuid.UUID(org_id)

    async with session_factory() as db:
        await set_tenant_context(db, org_uuid)
        event = await db.get(DomainEvent, event_uuid)
        if event is None:
            logger.error("domain event not found: %s", event_id)
            return

        result = await db.execute(
            select(Workflow).where(Workflow.org_id == org_uuid, Workflow.status == "active")
        )
        matched = 0
        for workflow in result.scalars().all():
            version_result = await db.execute(
                select(WorkflowVersion)
                .where(WorkflowVersion.workflow_id == workflow.id)
                .order_by(WorkflowVersion.version.desc())
                .limit(1)
            )
            version = version_result.scalar_one_or_none()
            if version is None:
                continue
            graph = WorkflowGraph.model_validate(version.graph)
            has_matching_trigger = any(
                node.type == "trigger" and node.config.get("event_type") == event.type
                for node in graph.nodes
            )
            if not has_matching_trigger:
                continue

            await create_run(
                db,
                org_uuid,
                workflow.id,
                {
                    "type": "event",
                    "event_id": str(event.id),
                    "event_type": event.type,
                    "payload": event.payload,
                },
                triggered_by_user_id=None,
            )
            matched += 1

        logger.info(
            "dispatched domain event %s (%s): %s matching workflow(s)",
            event_id,
            event.type,
            matched,
        )
