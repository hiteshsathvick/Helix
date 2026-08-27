import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.orgs.dependencies import require_permission
from app.modules.orgs.system_roles import PERMISSION_WORKFLOWS_MANAGE, PERMISSION_WORKFLOWS_RUN
from app.modules.workflows import service
from app.modules.workflows.schemas import (
    StepRunRead,
    WorkflowCreate,
    WorkflowRead,
    WorkflowRunDetail,
    WorkflowRunSummary,
    WorkflowRunTrigger,
    WorkflowUpdate,
    WorkflowVersionCreate,
    WorkflowVersionRead,
)

router = APIRouter(prefix="/orgs/{org_id}/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: WorkflowCreate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WORKFLOWS_MANAGE)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRead:
    workflow = await service.create_workflow(db, org_id, current_user.id, body.name, body.graph)
    return WorkflowRead.model_validate(workflow)


@router.get("", response_model=list[WorkflowRead])
async def list_workflows(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WORKFLOWS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowRead]:
    workflows = await service.list_workflows(db, org_id)
    return [WorkflowRead.model_validate(workflow) for workflow in workflows]


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WORKFLOWS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRead:
    workflow = await service.get_workflow(db, org_id, workflow_id)
    return WorkflowRead.model_validate(workflow)


@router.patch("/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WORKFLOWS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRead:
    workflow = await service.update_workflow(db, org_id, workflow_id, body.name, body.status)
    return WorkflowRead.model_validate(workflow)


@router.post(
    "/{workflow_id}/versions",
    response_model=WorkflowVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_version(
    workflow_id: uuid.UUID,
    body: WorkflowVersionCreate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WORKFLOWS_MANAGE)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowVersionRead:
    version = await service.create_version(db, org_id, workflow_id, current_user.id, body.graph)
    return WorkflowVersionRead.model_validate(version)


@router.get("/{workflow_id}/versions", response_model=list[WorkflowVersionRead])
async def list_versions(
    workflow_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WORKFLOWS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowVersionRead]:
    versions = await service.list_versions(db, org_id, workflow_id)
    return [WorkflowVersionRead.model_validate(version) for version in versions]


@router.post("/{workflow_id}/webhooks/rotate", response_model=WorkflowRead)
async def rotate_webhook_secret(
    workflow_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WORKFLOWS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRead:
    workflow = await service.rotate_webhook_secret(db, org_id, workflow_id)
    return WorkflowRead.model_validate(workflow)


@router.post(
    "/{workflow_id}/runs", response_model=WorkflowRunSummary, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_run(
    workflow_id: uuid.UUID,
    body: WorkflowRunTrigger,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WORKFLOWS_RUN)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunSummary:
    run = await service.create_run(
        db,
        org_id,
        workflow_id,
        {"type": "manual", **body.input},
        triggered_by_user_id=current_user.id,
    )
    return WorkflowRunSummary.model_validate(run)


@router.get("/{workflow_id}/runs", response_model=list[WorkflowRunSummary])
async def list_runs(
    workflow_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WORKFLOWS_RUN)),
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowRunSummary]:
    runs = await service.list_runs(db, org_id, workflow_id)
    return [WorkflowRunSummary.model_validate(run) for run in runs]


@router.get("/{workflow_id}/runs/{run_id}", response_model=WorkflowRunDetail)
async def get_run(
    workflow_id: uuid.UUID,
    run_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WORKFLOWS_RUN)),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunDetail:
    run, steps = await service.get_run_with_steps(db, org_id, workflow_id, run_id)
    return WorkflowRunDetail(
        id=run.id,
        workflow_id=run.workflow_id,
        version_id=run.version_id,
        status=run.status,
        trigger=run.trigger,
        context=run.context,
        cost=run.cost,
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
        steps=[StepRunRead.model_validate(step) for step in steps],
    )


# Unauthenticated -- the caller is an external system with no org
# membership. Mounted separately (not under /orgs/{org_id}/...) since the
# only credential is the per-workflow secret, verified in the service layer.
# org_id is part of the path (rather than looked up by workflow_id alone)
# because RLS is FORCE-enabled on `workflows`: without a known org_id there
# is no way to establish tenant context to even find the row.
webhooks_router = APIRouter(prefix="/webhooks/workflows", tags=["workflows"])


@webhooks_router.post("/{org_id}/{workflow_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_via_webhook(
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    body: dict[str, Any],
    x_webhook_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunSummary:
    await service.verify_webhook_secret(db, org_id, workflow_id, x_webhook_secret)
    run = await service.create_run(
        db, org_id, workflow_id, {"type": "webhook", "payload": body}, triggered_by_user_id=None
    )
    return WorkflowRunSummary.model_validate(run)
