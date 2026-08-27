import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.modules.agents import service
from app.modules.agents.schemas import (
    AgentCreate,
    AgentRead,
    AgentRunDetail,
    AgentRunSummary,
    AgentRunTrigger,
    AgentStepRead,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.orgs.dependencies import require_permission
from app.modules.orgs.system_roles import PERMISSION_AGENTS_MANAGE, PERMISSION_AGENTS_RUN

router = APIRouter(prefix="/orgs/{org_id}/agents", tags=["agents"])


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_AGENTS_MANAGE)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRead:
    agent = await service.create_agent(
        db, org_id, current_user.id, body.name, body.instructions, body.allowed_tools
    )
    return AgentRead.model_validate(agent)


@router.get("", response_model=list[AgentRead])
async def list_agents(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_AGENTS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> list[AgentRead]:
    agents = await service.list_agents(db, org_id)
    return [AgentRead.model_validate(agent) for agent in agents]


@router.post(
    "/{agent_id}/runs", response_model=AgentRunSummary, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_run(
    agent_id: uuid.UUID,
    body: AgentRunTrigger,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_AGENTS_RUN)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRunSummary:
    run = await service.create_run(db, org_id, current_user.id, agent_id, body.input)
    return AgentRunSummary.model_validate(run)


@router.get("/{agent_id}/runs", response_model=list[AgentRunSummary])
async def list_runs(
    agent_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_AGENTS_RUN)),
    db: AsyncSession = Depends(get_db),
) -> list[AgentRunSummary]:
    runs = await service.list_runs(db, org_id, agent_id)
    return [AgentRunSummary.model_validate(run) for run in runs]


@router.get("/{agent_id}/runs/{run_id}", response_model=AgentRunDetail)
async def get_run(
    agent_id: uuid.UUID,
    run_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_AGENTS_RUN)),
    db: AsyncSession = Depends(get_db),
) -> AgentRunDetail:
    run, steps = await service.get_run_with_steps(db, org_id, agent_id, run_id)
    return AgentRunDetail(
        id=run.id,
        agent_id=run.agent_id,
        status=run.status,
        input=run.input,
        output=run.output,
        error=run.error,
        tokens=run.tokens,
        cost=run.cost,
        created_at=run.created_at,
        finished_at=run.finished_at,
        steps=[AgentStepRead.model_validate(step) for step in steps],
    )
