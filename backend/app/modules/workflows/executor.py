"""Durable, resumable DAG execution (SPEC.md §20 — "the hard backend
correctness centerpiece"). execute_workflow_run is safe to invoke multiple
times for the same run (first attempt, or an Arq retry after a crash): it
always re-derives the ready node "frontier" from persisted StepRun rows
rather than trusting any in-memory loop position, so a fresh worker process
picking this back up lands in exactly the same state a continuing process
would have. See workflows/tasks.py for the Arq entrypoint that calls this.
"""

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.queue import enqueue_workflow_run_deferred
from app.core.tenancy import set_tenant_context
from app.modules.agents.tools import TOOLS, ToolContext
from app.modules.ai import service as ai_service
from app.modules.workflows.conditions import evaluate_condition, resolve_refs
from app.modules.workflows.models import StepRun, Workflow, WorkflowRun, WorkflowVersion
from app.modules.workflows.schemas import WorkflowEdge, WorkflowGraph, WorkflowNode

logger = logging.getLogger("helix.workflows")

_TERMINAL_STEP_STATUSES = ("succeeded", "skipped", "dlq", "failed")


async def execute_workflow_run(db: AsyncSession, org_id: uuid.UUID, run_id: uuid.UUID) -> None:
    settings = get_settings()
    await set_tenant_context(db, org_id)

    run = await db.get(WorkflowRun, run_id)
    if run is None:
        logger.error("workflow run not found: %s", run_id)
        return
    if run.status in ("completed", "failed", "cancelled"):
        return  # already terminal -- a re-invocation after completion is a no-op

    workflow = await db.get(Workflow, run.workflow_id)
    version = await db.get(WorkflowVersion, run.version_id)
    if workflow is None or version is None:
        run.status = "failed"
        run.error = "workflow or version no longer exists"
        run.finished_at = datetime.now(UTC)
        await db.commit()
        return

    graph = WorkflowGraph.model_validate(version.graph)
    nodes_by_id = {node.id: node for node in graph.nodes}
    incoming: dict[str, list[WorkflowEdge]] = {node.id: [] for node in graph.nodes}
    has_outgoing: dict[str, bool] = dict.fromkeys(nodes_by_id, False)
    for edge in graph.edges:
        incoming[edge.to].append(edge)
        has_outgoing[edge.from_node] = True
    sink_ids = [node_id for node_id, outgoing in has_outgoing.items() if not outgoing]

    acting_user_id = run.triggered_by_user_id or workflow.created_by_user_id

    if run.status == "pending":
        run.status = "running"
        await db.commit()
        await set_tenant_context(db, org_id)

    result = await db.execute(select(StepRun).where(StepRun.workflow_run_id == run.id))
    steps_by_node: dict[str, StepRun] = {step.node_id: step for step in result.scalars().all()}

    # A step can only be "running" here if a *previous* invocation of this
    # function died mid-node (execute_workflow_run never re-enters itself
    # while a node is running -- _execute_node always leaves a step at
    # "succeeded"/"pending"/"dlq" before returning). Finding one at the top
    # of a fresh invocation means exactly that: a crash. Take it over --
    # this is the "resumable" half of SPEC.md §20's guarantee.
    reclaimed_any = False
    for step in steps_by_node.values():
        if step.status == "running":
            step.status = "pending"
            reclaimed_any = True
    if reclaimed_any:
        await db.commit()
        await set_tenant_context(db, org_id)

    # Trigger nodes have no incoming edges and never "execute" — their
    # output is simply the run's trigger payload, recorded once up front so
    # the readiness computation below treats them as already resolved.
    created_trigger_step = False
    for node in graph.nodes:
        if node.type == "trigger" and node.id not in steps_by_node:
            step = StepRun(
                org_id=org_id,
                workflow_run_id=run.id,
                node_id=node.id,
                node_type="trigger",
                status="succeeded",
                attempts=1,
                input={},
                output=run.trigger,
            )
            db.add(step)
            steps_by_node[node.id] = step
            _record_step_output(run, step)
            created_trigger_step = True
    if created_trigger_step:
        await db.commit()
        await set_tenant_context(db, org_id)

    deadline = time.monotonic() + settings.workflow_run_timeout_seconds
    total_steps = len(steps_by_node)
    made_progress = True

    while made_progress:
        made_progress = False

        if time.monotonic() > deadline:
            await _fail_run(db, org_id, run, "run exceeded its wall-clock timeout")
            return
        if total_steps > settings.workflow_run_max_steps:
            await _fail_run(db, org_id, run, "run exceeded its maximum step count")
            return

        newly_created = _create_ready_step_runs(
            db, graph.nodes, incoming, steps_by_node, run, org_id
        )
        if newly_created:
            total_steps += len(newly_created)
            made_progress = True
            await db.commit()
            await set_tenant_context(db, org_id)

        now = datetime.now(UTC)
        for node_id, step in list(steps_by_node.items()):
            if step.status != "pending":
                continue
            if step.next_attempt_at is not None and step.next_attempt_at > now:
                continue
            node = nodes_by_id[node_id]
            await _execute_node(db, org_id, run, workflow, node, step, acting_user_id, settings)
            made_progress = True
            await db.commit()
            await set_tenant_context(db, org_id)

    await _finalize_run(db, org_id, run, sink_ids, steps_by_node)


def _create_ready_step_runs(
    db: AsyncSession,
    nodes: list[WorkflowNode],
    incoming: dict[str, list[WorkflowEdge]],
    steps_by_node: dict[str, StepRun],
    run: WorkflowRun,
    org_id: uuid.UUID,
) -> list[StepRun]:
    """A node is ready once every upstream edge is resolved (its source
    reached a terminal status) — it then either executes ("pending", if at
    least one incoming edge is on a taken branch) or is marked "skipped"
    (an OR-join: any one satisfied path is enough to run; if none are, the
    node is skipped, and that skip propagates to its own downstream nodes
    on the next pass).
    """
    created: list[StepRun] = []
    for node in nodes:
        if node.id in steps_by_node or node.type == "trigger":
            continue
        edges_in = incoming[node.id]
        if not edges_in:
            continue  # only reachable from a trigger node, already handled

        sources = [steps_by_node.get(edge.from_node) for edge in edges_in]
        if any(
            source is None or source.status not in _TERMINAL_STEP_STATUSES for source in sources
        ):
            continue  # still waiting on an upstream node

        satisfied = any(
            source is not None
            and source.status == "succeeded"
            and (edge.condition is None or _edge_matches(source, edge.condition))
            for source, edge in zip(sources, edges_in, strict=True)
        )
        status = "pending" if satisfied else "skipped"
        step = StepRun(
            org_id=org_id,
            workflow_run_id=run.id,
            node_id=node.id,
            node_type=node.type,
            status=status,
            attempts=0,
            input=node.config,
            output={},
        )
        db.add(step)
        steps_by_node[node.id] = step
        created.append(step)
        if status == "skipped":
            _record_step_output(run, step)
    return created


def _edge_matches(source_step: StepRun, edge_condition: str) -> bool:
    """A condition node's StepRun.output is {"result": bool}; the edge it
    matches is labeled "true"/"false". Any other node type has no branches,
    so an edge leaving it is never labeled and always matches."""
    if source_step.node_type != "condition":
        return True
    return str(source_step.output.get("result")).lower() == edge_condition


async def _execute_node(
    db: AsyncSession,
    org_id: uuid.UUID,
    run: WorkflowRun,
    workflow: Workflow,
    node: WorkflowNode,
    step: StepRun,
    acting_user_id: uuid.UUID,
    settings: Any,
) -> None:
    step.status = "running"
    step.attempts += 1

    try:
        if node.type == "condition":
            output = {"result": evaluate_condition(run.context, node.config["condition"])}
        elif node.type == "notify":
            args = resolve_refs(node.config, run.context)
            output = await TOOLS["notify"].handler(ToolContext(db, org_id, acting_user_id), args)
            if "error" in output:
                raise RuntimeError(str(output["error"]))
        elif node.type == "action":
            tool_name = node.config["tool"]
            args = resolve_refs(node.config.get("args", {}), run.context)
            output = await TOOLS[tool_name].handler(ToolContext(db, org_id, acting_user_id), args)
            if "error" in output:
                raise RuntimeError(str(output["error"]))
        elif node.type == "ai":
            output, cost = await _execute_ai_node(db, org_id, run, node, acting_user_id, settings)
            run.cost += cost
        else:
            output = {}
    except Exception as exc:  # noqa: BLE001 -- one bad node must not crash the run
        step.error = str(exc)
        if step.attempts >= settings.workflow_step_max_attempts:
            step.status = "dlq"
            logger.error(
                "workflow step exhausted retries: run=%s node=%s error=%s", run.id, node.id, exc
            )
        else:
            step.status = "pending"
            backoff = settings.workflow_step_backoff_base_seconds * (2 ** (step.attempts - 1))
            step.next_attempt_at = datetime.now(UTC) + timedelta(seconds=backoff)
            logger.warning(
                "workflow step failed, retrying in %ss: run=%s node=%s attempt=%s error=%s",
                backoff,
                run.id,
                node.id,
                step.attempts,
                exc,
            )
        return

    step.status = "succeeded"
    step.output = output
    step.error = None
    _record_step_output(run, step)


async def _execute_ai_node(
    db: AsyncSession,
    org_id: uuid.UUID,
    run: WorkflowRun,
    node: WorkflowNode,
    acting_user_id: uuid.UUID,
    settings: Any,
) -> tuple[dict[str, Any], float]:
    ai_config = await ai_service.resolve_org_ai_config(db, org_id)
    allowed_tools: list[str] = node.config.get("allowed_tools", [])
    tool_specs = [TOOLS[name].spec for name in allowed_tools if name in TOOLS]
    instructions = str(node.config.get("instructions", ""))
    input_value = resolve_refs(node.config.get("input", ""), run.context)

    messages: list[ai_service.Message] = [{"role": "user", "content": str(input_value)}]
    total_input_tokens = total_output_tokens = 0
    final_text: str | None = None

    for _round in range(settings.workflow_ai_node_max_tool_rounds):
        result = await ai_service.complete_with_tools(
            instructions,
            messages,
            settings.assistant_max_output_tokens,
            tool_specs,
            provider=ai_config.provider,
            model=ai_config.model,
        )
        total_input_tokens += result.usage.input_tokens
        total_output_tokens += result.usage.output_tokens

        if not result.tool_calls:
            final_text = result.text
            break

        messages.append(result.assistant_message)
        tool_results: dict[str, dict[str, Any]] = {}
        for call in result.tool_calls:
            if call.name not in allowed_tools or call.name not in TOOLS:
                tool_results[call.id] = {"error": f"tool {call.name!r} not allowed for this node"}
                continue
            try:
                tool_results[call.id] = await TOOLS[call.name].handler(
                    ToolContext(db, org_id, acting_user_id), call.arguments
                )
            except Exception as exc:  # noqa: BLE001 -- a tool's own bug must not crash the node
                tool_results[call.id] = {"error": f"tool execution failed: {exc}"}
        messages.extend(
            ai_service.tool_result_messages(ai_config.provider, result.tool_calls, tool_results)
        )
    else:
        raise RuntimeError("ai node exceeded its maximum tool-call rounds without a final answer")

    cost = ai_service.compute_cost(ai_config.model, total_input_tokens, total_output_tokens)
    return {"text": final_text}, cost


def _record_step_output(run: WorkflowRun, step: StepRun) -> None:
    run.context.setdefault("steps", {})[step.node_id] = step.output
    # Mutable JSONB isn't change-tracked by SQLAlchemy by default -- without
    # this, an in-place dict mutation like the line above is silently lost
    # on commit.
    flag_modified(run, "context")


async def _fail_run(db: AsyncSession, org_id: uuid.UUID, run: WorkflowRun, error: str) -> None:
    run.status = "failed"
    run.error = error
    run.finished_at = datetime.now(UTC)
    await db.commit()


async def _finalize_run(
    db: AsyncSession,
    org_id: uuid.UUID,
    run: WorkflowRun,
    sink_ids: list[str],
    steps_by_node: dict[str, StepRun],
) -> None:
    dlq_steps = [step for step in steps_by_node.values() if step.status == "dlq"]
    if dlq_steps:
        await _fail_run(
            db, org_id, run, f"node {dlq_steps[0].node_id!r} exhausted its retry attempts"
        )
        return

    unresolved_sinks = [
        sink_id
        for sink_id in sink_ids
        if steps_by_node.get(sink_id) is None
        or steps_by_node[sink_id].status not in ("succeeded", "skipped")
    ]
    pending_with_backoff = [
        step
        for step in steps_by_node.values()
        if step.status == "pending" and step.next_attempt_at is not None
    ]

    if not unresolved_sinks and not pending_with_backoff:
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        await db.commit()
        return

    if pending_with_backoff:
        attempt_times = [
            step.next_attempt_at for step in pending_with_backoff if step.next_attempt_at
        ]
        earliest = min(attempt_times)
        defer_seconds = max((earliest - datetime.now(UTC)).total_seconds(), 1.0)
        await db.commit()
        await enqueue_workflow_run_deferred(run.id, org_id, defer_seconds)
        return

    # No ready nodes, no pending backoff, but a sink is still unresolved --
    # a malformed/unreachable graph shape validation should have caught.
    # Fail defensively rather than let the run sit "running" forever.
    await _fail_run(
        db, org_id, run, "workflow run stalled: no ready nodes but a sink is unresolved"
    )
