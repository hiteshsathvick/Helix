import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.queue import enqueue_agent_run
from app.core.tenancy import set_tenant_context
from app.modules.agents.models import Agent, AgentRun, AgentStep
from app.modules.agents.tools import TOOLS, ToolContext
from app.modules.ai import cost_guard
from app.modules.ai import service as ai_service
from app.modules.billing import service as billing_service

logger = logging.getLogger("helix.agents")


async def create_agent(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    instructions: str,
    allowed_tools: list[str],
) -> Agent:
    agent = Agent(
        org_id=org_id,
        name=name,
        instructions=instructions,
        allowed_tools=allowed_tools,
        created_by_user_id=user_id,
    )
    db.add(agent)
    await db.commit()
    # db.commit() ends the transaction, and with it the SET LOCAL/set_config
    # tenant context RLS needs (see documents/service.py's identical lesson)
    # — Agent is RLS-protected, so refresh() would otherwise come back empty.
    await set_tenant_context(db, org_id)
    await db.refresh(agent)
    logger.info("agent created: %s in org %s", agent.id, org_id)
    return agent


async def list_agents(db: AsyncSession, org_id: uuid.UUID) -> list[Agent]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Agent)
        .where(Agent.org_id == org_id, Agent.deleted_at.is_(None))
        .order_by(Agent.created_at.desc())
    )
    return list(result.scalars().all())


async def get_agent(db: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id, Agent.org_id == org_id, Agent.deleted_at.is_(None)
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise NotFoundError("agent not found")
    return agent


async def create_run(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, agent_id: uuid.UUID, input_text: str
) -> AgentRun:
    """Creates the run row and enqueues it — mirrors
    `ingestion.service.trigger_ingestion`'s create-then-enqueue shape. The
    actual tool-calling loop runs in the worker (`execute_run` below), never
    inline in this request.
    """
    await set_tenant_context(db, org_id)
    await get_agent(db, org_id, agent_id)  # 404s if missing/not this org

    # Checked here, before a job is even enqueued. Spend comes from
    # billing's org-wide usage_events total (Phase 16) -- the org's whole
    # AI budget across assistant/agents/workflows together, not just this
    # module's own runs (see billing/service.py::get_monthly_usage_usd's
    # docstring for what this replaced).
    ai_config = await ai_service.resolve_org_ai_config(db, org_id)
    spent = await billing_service.get_monthly_usage_usd(db, org_id)
    cost_guard.enforce_cost_cap(spent, ai_config.monthly_cost_cap_usd)

    run = AgentRun(
        org_id=org_id,
        agent_id=agent_id,
        triggered_by_user_id=user_id,
        input=input_text,
        status="pending",
    )
    db.add(run)
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(run)

    await enqueue_agent_run(run.id, org_id, agent_id)
    logger.info("agent run enqueued: %s for agent %s", run.id, agent_id)
    return run


async def list_runs(db: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID) -> list[AgentRun]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.org_id == org_id, AgentRun.agent_id == agent_id)
        .order_by(AgentRun.created_at.desc())
    )
    return list(result.scalars().all())


async def get_run_with_steps(
    db: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID, run_id: uuid.UUID
) -> tuple[AgentRun, list[AgentStep]]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(AgentRun).where(
            AgentRun.id == run_id, AgentRun.org_id == org_id, AgentRun.agent_id == agent_id
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise NotFoundError("agent run not found")

    steps_result = await db.execute(
        select(AgentStep)
        .where(AgentStep.org_id == org_id, AgentStep.run_id == run_id)
        .order_by(AgentStep.ordinal)
    )
    return run, list(steps_result.scalars().all())


async def execute_run(db: AsyncSession, org_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """The bounded tool-calling loop (SPEC.md §19). Called only from the
    worker task (agents/tasks.py) — never from a request handler, since a
    run can take many seconds across several LLM round trips.

    Guardrails, all hard-enforced here rather than left to the prompt:
    max steps, wall-clock timeout, per-run cost cap, and allowed-tools
    (checked again per call even though the prompt only ever offers the
    agent's own allowed tools — a model can still ask for a tool it wasn't
    given).
    """
    settings = get_settings()
    await set_tenant_context(db, org_id)

    run = await db.get(AgentRun, run_id)
    if run is None:
        logger.error("agent run not found: %s", run_id)
        return
    agent = await db.get(Agent, run.agent_id)
    if agent is None:
        run.status = "failed"
        run.error = "agent no longer exists"
        run.finished_at = datetime.now(UTC)
        await db.commit()
        return

    run.status = "running"
    await db.commit()
    await set_tenant_context(db, org_id)

    tool_specs = [TOOLS[name].spec for name in agent.allowed_tools if name in TOOLS]
    ai_config = await ai_service.resolve_org_ai_config(db, org_id)
    messages: list[ai_service.Message] = [{"role": "user", "content": run.input}]

    total_input_tokens = 0
    total_output_tokens = 0
    final_text: str | None = None
    run_error: str | None = None
    ordinal = 0
    deadline = time.monotonic() + settings.agent_run_timeout_seconds

    try:
        for _step_number in range(settings.agent_max_steps):
            if time.monotonic() > deadline:
                run_error = "run exceeded its wall-clock timeout"
                break

            result = await ai_service.complete_with_tools(
                agent.instructions,
                messages,
                settings.assistant_max_output_tokens,
                tool_specs,
                provider=ai_config.provider,
                model=ai_config.model,
            )
            total_input_tokens += result.usage.input_tokens
            total_output_tokens += result.usage.output_tokens
            cost_so_far = ai_service.compute_cost(
                ai_config.model, total_input_tokens, total_output_tokens
            )
            if cost_so_far >= settings.agent_max_run_cost_usd:
                run_error = "run exceeded its per-run cost cap"
                break

            if not result.tool_calls:
                final_text = result.text
                ordinal += 1
                db.add(
                    AgentStep(
                        org_id=org_id,
                        run_id=run.id,
                        ordinal=ordinal,
                        type="final_answer",
                        tool=None,
                        input={},
                        output={"text": result.text},
                    )
                )
                break

            messages.append(result.assistant_message)
            tool_results: dict[str, dict[str, Any]] = {}
            for call in result.tool_calls:
                ordinal += 1
                if call.name not in agent.allowed_tools or call.name not in TOOLS:
                    output = {"error": f"tool {call.name!r} is not allowed for this agent"}
                else:
                    try:
                        output = await TOOLS[call.name].handler(
                            ToolContext(db, org_id, run.triggered_by_user_id), call.arguments
                        )
                    except Exception as exc:  # a tool's own bug must not crash the whole run
                        logger.exception("tool %s failed in run %s", call.name, run.id)
                        output = {"error": f"tool execution failed: {exc}"}
                tool_results[call.id] = output
                db.add(
                    AgentStep(
                        org_id=org_id,
                        run_id=run.id,
                        ordinal=ordinal,
                        type="tool_call",
                        tool=call.name,
                        input=call.arguments,
                        output=output,
                    )
                )
            await db.commit()
            await set_tenant_context(db, org_id)

            messages.extend(
                ai_service.tool_result_messages(ai_config.provider, result.tool_calls, tool_results)
            )
        else:
            run_error = "run exceeded its maximum step count"
    except Exception as exc:
        logger.exception("agent run %s failed", run.id)
        run_error = str(exc)

    run.status = "failed" if run_error else "completed"
    run.output = final_text
    run.error = run_error
    run.tokens = total_input_tokens + total_output_tokens
    run.cost = ai_service.compute_cost(ai_config.model, total_input_tokens, total_output_tokens)
    run.finished_at = datetime.now(UTC)
    await billing_service.record_usage(db, org_id, "agent_run", run.tokens, run.cost)
    await db.commit()
    logger.info("agent run %s finished: status=%s", run.id, run.status)
