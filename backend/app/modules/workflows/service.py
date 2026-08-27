import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, UnauthorizedError
from app.core.queue import enqueue_workflow_run
from app.core.tenancy import set_tenant_context
from app.modules.ai import cost_guard
from app.modules.ai import service as ai_service
from app.modules.workflows.models import StepRun, Workflow, WorkflowRun, WorkflowVersion
from app.modules.workflows.schemas import WorkflowGraph

logger = logging.getLogger("helix.workflows")


async def create_workflow(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, name: str, graph: WorkflowGraph
) -> Workflow:
    workflow = Workflow(
        org_id=org_id,
        name=name,
        status="draft",
        created_by_user_id=user_id,
        webhook_secret=secrets.token_urlsafe(32),
    )
    db.add(workflow)
    await db.flush()

    version = WorkflowVersion(
        org_id=org_id,
        workflow_id=workflow.id,
        version=1,
        graph=graph.model_dump(by_alias=True),
        created_by_user_id=user_id,
    )
    db.add(version)
    await db.commit()
    # db.commit() ends the transaction and with it the tenant RLS context --
    # see agents/service.py's identical, previously-fixed lesson.
    await set_tenant_context(db, org_id)
    await db.refresh(workflow)
    logger.info("workflow created: %s in org %s", workflow.id, org_id)
    return workflow


async def list_workflows(db: AsyncSession, org_id: uuid.UUID) -> list[Workflow]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Workflow)
        .where(Workflow.org_id == org_id, Workflow.deleted_at.is_(None))
        .order_by(Workflow.created_at.desc())
    )
    return list(result.scalars().all())


async def get_workflow(db: AsyncSession, org_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id, Workflow.org_id == org_id, Workflow.deleted_at.is_(None)
        )
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise NotFoundError("workflow not found")
    return workflow


async def update_workflow(
    db: AsyncSession,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    name: str | None,
    status: str | None,
) -> Workflow:
    workflow = await get_workflow(db, org_id, workflow_id)
    if name is not None:
        workflow.name = name
    if status is not None:
        workflow.status = status
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(workflow)
    return workflow


async def rotate_webhook_secret(
    db: AsyncSession, org_id: uuid.UUID, workflow_id: uuid.UUID
) -> Workflow:
    workflow = await get_workflow(db, org_id, workflow_id)
    workflow.webhook_secret = secrets.token_urlsafe(32)
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(workflow)
    return workflow


async def get_current_version(
    db: AsyncSession, org_id: uuid.UUID, workflow_id: uuid.UUID
) -> WorkflowVersion:
    """ "The current version" is simply the highest `version` number for this
    workflow -- see workflows/models.py's Workflow docstring for why there's
    no separate current_version_id pointer column."""
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id, WorkflowVersion.org_id == org_id)
        .order_by(WorkflowVersion.version.desc())
        .limit(1)
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise NotFoundError("workflow has no versions")
    return version


async def create_version(
    db: AsyncSession,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    user_id: uuid.UUID,
    graph: WorkflowGraph,
) -> WorkflowVersion:
    await get_workflow(db, org_id, workflow_id)  # 404s if missing/not this org
    current = await get_current_version(db, org_id, workflow_id)

    version = WorkflowVersion(
        org_id=org_id,
        workflow_id=workflow_id,
        version=current.version + 1,
        graph=graph.model_dump(by_alias=True),
        created_by_user_id=user_id,
    )
    db.add(version)
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(version)
    logger.info("workflow version created: %s v%s", workflow_id, version.version)
    return version


async def list_versions(
    db: AsyncSession, org_id: uuid.UUID, workflow_id: uuid.UUID
) -> list[WorkflowVersion]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id, WorkflowVersion.org_id == org_id)
        .order_by(WorkflowVersion.version.desc())
    )
    return list(result.scalars().all())


async def _get_monthly_spend(db: AsyncSession, org_id: uuid.UUID) -> float:
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(WorkflowRun.cost), 0.0)).where(
            WorkflowRun.org_id == org_id, WorkflowRun.created_at >= month_start
        )
    )
    return float(result.scalar_one())


async def create_run(
    db: AsyncSession,
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    trigger: dict[str, Any],
    *,
    triggered_by_user_id: uuid.UUID | None,
) -> WorkflowRun:
    """Creates the run row and enqueues execution -- called from the manual
    trigger endpoint, the webhook endpoint, and dispatch_domain_event_task
    (workflows/tasks.py), all of which just supply a different `trigger`
    dict and identity.
    """
    await set_tenant_context(db, org_id)
    workflow = await get_workflow(db, org_id, workflow_id)
    if workflow.status == "disabled":
        raise ConflictError("workflow is disabled")

    version = await get_current_version(db, org_id, workflow_id)

    # Same per-module cost-cap pattern agents/assistant already use: each
    # AI-spending surface checks its own spend against the org's shared cap
    # value (ai/cost_guard's own docstring already frames this as "a
    # lightweight guard, not a unified ledger across every surface" -- a
    # true cross-surface ledger is a known, pre-existing gap, not something
    # this phase should fix as a side effect).
    ai_config = await ai_service.resolve_org_ai_config(db, org_id)
    spent = await _get_monthly_spend(db, org_id)
    cost_guard.enforce_cost_cap(spent, ai_config.monthly_cost_cap_usd)

    run = WorkflowRun(
        org_id=org_id,
        workflow_id=workflow_id,
        version_id=version.id,
        status="pending",
        trigger=trigger,
        context={"trigger": trigger},
        triggered_by_user_id=triggered_by_user_id,
    )
    db.add(run)
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(run)

    await enqueue_workflow_run(run.id, org_id)
    logger.info("workflow run enqueued: %s for workflow %s", run.id, workflow_id)
    return run


async def list_runs(
    db: AsyncSession, org_id: uuid.UUID, workflow_id: uuid.UUID
) -> list[WorkflowRun]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.org_id == org_id, WorkflowRun.workflow_id == workflow_id)
        .order_by(WorkflowRun.created_at.desc())
    )
    return list(result.scalars().all())


async def get_run_with_steps(
    db: AsyncSession, org_id: uuid.UUID, workflow_id: uuid.UUID, run_id: uuid.UUID
) -> tuple[WorkflowRun, list[StepRun]]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id,
            WorkflowRun.org_id == org_id,
            WorkflowRun.workflow_id == workflow_id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise NotFoundError("workflow run not found")

    steps_result = await db.execute(
        select(StepRun)
        .where(StepRun.org_id == org_id, StepRun.workflow_run_id == run_id)
        .order_by(StepRun.created_at)
    )
    return run, list(steps_result.scalars().all())


async def verify_webhook_secret(
    db: AsyncSession, org_id: uuid.UUID, workflow_id: uuid.UUID, secret: str
) -> Workflow:
    workflow = await get_workflow(db, org_id, workflow_id)
    if not secrets.compare_digest(workflow.webhook_secret, secret):
        raise UnauthorizedError("invalid webhook secret")
    if workflow.status != "active":
        raise ConflictError("workflow is not active")
    return workflow
