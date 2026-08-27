import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.events import publish_event
from app.core.redis import get_redis_client
from app.core.tenancy import set_tenant_context
from app.main import app
from app.modules.agents.tools import TOOLS as AGENT_TOOLS
from app.modules.agents.tools import Tool, ToolContext
from app.modules.ai import service as ai_service
from app.modules.ai.providers import ToolCompletionResult, UsageInfo
from app.modules.ingestion.pipeline import run_ingestion
from app.modules.orgs.system_roles import VIEWER_ROLE_ID
from app.modules.workflows.conditions import evaluate_condition, resolve_path, resolve_refs
from app.modules.workflows.executor import execute_workflow_run
from app.modules.workflows.models import StepRun, WorkflowRun
from app.modules.workflows.tasks import dispatch_domain_event_task

AUTH_PREFIX = "/api/v1/auth"
ORGS_PREFIX = "/api/v1/orgs"


@pytest.fixture(autouse=True)
async def _clear_rate_limit_state():
    client = get_redis_client()
    try:
        await client.flushdb()
    finally:
        await client.aclose()
    yield


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    async def _fake_complete_with_tools(
        system, messages, max_tokens, tools, *, provider=None, model=None
    ):
        return ToolCompletionResult(
            text="ai node answer",
            tool_calls=[],
            assistant_message={"role": "assistant", "content": "ai node answer"},
            usage=UsageInfo(input_tokens=10, output_tokens=5),
        )

    def _fake_tool_result_messages(provider, tool_calls, results):
        return [{"role": "tool_result", "content": str(results)}]

    monkeypatch.setattr(ai_service, "complete_with_tools", _fake_complete_with_tools)
    monkeypatch.setattr(ai_service, "tool_result_messages", _fake_tool_result_messages)


def _unique_email() -> str:
    return f"user-{uuid.uuid4()}@example.com"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register_login_and_create_org(client: TestClient) -> tuple[str, str]:
    email = _unique_email()
    password = "a-strong-password-1"
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": password})
    token = client.post(f"{AUTH_PREFIX}/login", json={"email": email, "password": password}).json()[
        "access_token"
    ]
    org_id = client.post(
        ORGS_PREFIX,
        json={"name": "Org", "slug": f"org-{uuid.uuid4().hex[:8]}"},
        headers=_auth_headers(token),
    ).json()["id"]
    return token, org_id


_LINEAR_NOTIFY_GRAPH = {
    "nodes": [
        {"id": "start", "type": "trigger", "config": {}},
        {"id": "n1", "type": "notify", "config": {"channel": "c1", "message": "step one"}},
        {"id": "n2", "type": "notify", "config": {"channel": "c2", "message": "step two"}},
    ],
    "edges": [{"from": "start", "to": "n1"}, {"from": "n1", "to": "n2"}],
}


def _create_workflow(
    client: TestClient,
    token: str,
    org_id: str,
    graph: dict | None = None,
    name: str = "Test Workflow",
) -> str:
    return client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows",
        json={"name": name, "graph": graph or _LINEAR_NOTIFY_GRAPH},
        headers=_auth_headers(token),
    ).json()["id"]


def _activate(client: TestClient, token: str, org_id: str, workflow_id: str) -> None:
    client.patch(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}",
        json={"status": "active"},
        headers=_auth_headers(token),
    )


async def _run_synchronously(org_id: str, run_id: str) -> None:
    async with session_factory() as db:
        await execute_workflow_run(db, uuid.UUID(org_id), uuid.UUID(run_id))


# --- unit: conditions ---


def test_resolve_path_missing_segment_returns_none():
    assert resolve_path({"a": {"b": 1}}, "a.b") == 1
    assert resolve_path({"a": {"b": 1}}, "a.c") is None
    assert resolve_path({"a": {"b": 1}}, "x.y") is None


def test_resolve_refs_resolves_dollar_ref_placeholders():
    context = {"steps": {"n1": {"count": 5}}}
    resolved = resolve_refs({"value": {"$ref": "steps.n1.count"}, "literal": "x"}, context)
    assert resolved == {"value": 5, "literal": "x"}


@pytest.mark.parametrize(
    "op,left,right,expected",
    [
        ("eq", 5, 5, True),
        ("ne", 5, 6, True),
        ("gt", 5, 3, True),
        ("gte", 5, 5, True),
        ("lt", 3, 5, True),
        ("lte", 5, 5, True),
        ("contains", "hello world", "world", True),
        ("exists", "anything", None, True),
    ],
)
def test_evaluate_condition_operators(op, left, right, expected):
    context = {"value": left}
    condition = {"left": {"path": "value"}, "op": op, "right": right}
    assert evaluate_condition(context, condition) is expected


def test_evaluate_condition_missing_path_is_falsy_not_an_error():
    condition = {"left": {"path": "does.not.exist"}, "op": "eq", "right": "x"}
    assert evaluate_condition({}, condition) is False


def test_evaluate_condition_rejects_unknown_operator():
    condition = {"left": {"path": "value"}, "op": "__import__", "right": "x"}
    with pytest.raises(ValueError, match="unsupported condition operator"):
        evaluate_condition({"value": 1}, condition)


# --- graph validation ---


def test_create_workflow_rejects_unknown_node_type(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    graph = {"nodes": [{"id": "n1", "type": "bogus", "config": {}}], "edges": []}
    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows",
        json={"name": "Bad", "graph": graph},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422


def test_create_workflow_rejects_unknown_tool_on_action_node(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "config": {}},
            {"id": "n1", "type": "action", "config": {"tool": "not_a_real_tool"}},
        ],
        "edges": [{"from": "start", "to": "n1"}],
    }
    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows",
        json={"name": "Bad", "graph": graph},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422


def test_create_workflow_rejects_dangling_edge(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    graph = {
        "nodes": [{"id": "start", "type": "trigger", "config": {}}],
        "edges": [{"from": "start", "to": "does_not_exist"}],
    }
    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows",
        json={"name": "Bad", "graph": graph},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422


def test_create_workflow_rejects_cyclic_graph(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    graph = {
        "nodes": [
            {"id": "a", "type": "notify", "config": {"channel": "c", "message": "m"}},
            {"id": "b", "type": "notify", "config": {"channel": "c", "message": "m"}},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
    }
    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows",
        json={"name": "Bad", "graph": graph},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422


# --- permissions ---


def test_viewer_cannot_create_workflow(client: TestClient) -> None:
    owner_token, org_id = _register_login_and_create_org(client)
    viewer_email = _unique_email()
    viewer_password = "a-strong-password-1"
    client.post(
        f"{AUTH_PREFIX}/register", json={"email": viewer_email, "password": viewer_password}
    )
    viewer_token = client.post(
        f"{AUTH_PREFIX}/login", json={"email": viewer_email, "password": viewer_password}
    ).json()["access_token"]

    invite = client.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": viewer_email},
        headers=_auth_headers(owner_token),
    ).json()
    client.post(
        f"/api/v1/invitations/{invite['token']}/accept", headers=_auth_headers(viewer_token)
    )
    members = client.get(
        f"{ORGS_PREFIX}/{org_id}/members", headers=_auth_headers(owner_token)
    ).json()
    viewer_membership_id = next(m["id"] for m in members if m["email"] == viewer_email)
    client.put(
        f"{ORGS_PREFIX}/{org_id}/memberships/{viewer_membership_id}/role",
        json={"role_id": str(VIEWER_ROLE_ID)},
        headers=_auth_headers(owner_token),
    )

    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows",
        json={"name": "W", "graph": _LINEAR_NOTIFY_GRAPH},
        headers=_auth_headers(viewer_token),
    )
    assert response.status_code == 403


def test_workflow_in_one_org_is_invisible_to_another(client: TestClient) -> None:
    token_a, org_a = _register_login_and_create_org(client)
    _token_b, org_b = _register_login_and_create_org(client)
    workflow_id = _create_workflow(client, token_a, org_a)

    response = client.get(
        f"{ORGS_PREFIX}/{org_b}/workflows/{workflow_id}", headers=_auth_headers(token_a)
    )
    assert response.status_code == 404


# --- API round trip / run lifecycle ---


@pytest.mark.asyncio
async def test_full_lifecycle_create_activate_trigger_completes(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    workflow_id = _create_workflow(client, token, org_id)
    _activate(client, token, org_id, workflow_id)

    trigger = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {}},
        headers=_auth_headers(token),
    )
    assert trigger.status_code == 202
    run_id = trigger.json()["id"]
    assert trigger.json()["status"] == "pending"

    await _run_synchronously(org_id, run_id)

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs/{run_id}",
        headers=_auth_headers(token),
    ).json()
    assert detail["status"] == "completed"
    step_types = {step["node_id"]: step["status"] for step in detail["steps"]}
    assert step_types == {"start": "succeeded", "n1": "succeeded", "n2": "succeeded"}


@pytest.mark.asyncio
async def test_condition_node_skips_the_untaken_branch(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "config": {}},
            {
                "id": "check",
                "type": "condition",
                "config": {
                    "condition": {"left": {"path": "trigger.value"}, "op": "eq", "right": "yes"}
                },
            },
            {"id": "if_true", "type": "notify", "config": {"channel": "c", "message": "true"}},
            {"id": "if_false", "type": "notify", "config": {"channel": "c", "message": "false"}},
        ],
        "edges": [
            {"from": "start", "to": "check"},
            {"from": "check", "to": "if_true", "condition": "true"},
            {"from": "check", "to": "if_false", "condition": "false"},
        ],
    }
    workflow_id = _create_workflow(client, token, org_id, graph)
    _activate(client, token, org_id, workflow_id)

    trigger = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {"value": "yes"}},
        headers=_auth_headers(token),
    )
    run_id = trigger.json()["id"]
    await _run_synchronously(org_id, run_id)

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs/{run_id}",
        headers=_auth_headers(token),
    ).json()
    assert detail["status"] == "completed"
    statuses = {step["node_id"]: step["status"] for step in detail["steps"]}
    assert statuses["if_true"] == "succeeded"
    assert statuses["if_false"] == "skipped"


@pytest.mark.asyncio
async def test_ai_node_completes_using_the_mocked_llm(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "config": {}},
            {
                "id": "ai1",
                "type": "ai",
                "config": {"instructions": "Summarize.", "allowed_tools": [], "input": "hello"},
            },
        ],
        "edges": [{"from": "start", "to": "ai1"}],
    }
    workflow_id = _create_workflow(client, token, org_id, graph)
    _activate(client, token, org_id, workflow_id)

    trigger = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {}},
        headers=_auth_headers(token),
    )
    run_id = trigger.json()["id"]
    await _run_synchronously(org_id, run_id)

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs/{run_id}",
        headers=_auth_headers(token),
    ).json()
    assert detail["status"] == "completed"
    ai_step = next(step for step in detail["steps"] if step["node_id"] == "ai1")
    assert ai_step["output"]["text"] == "ai node answer"
    assert detail["cost"] > 0


# --- versioning ---


@pytest.mark.asyncio
async def test_editing_workflow_creates_new_version_inflight_run_keeps_old_version(
    client: TestClient,
) -> None:
    token, org_id = _register_login_and_create_org(client)
    workflow_id = _create_workflow(client, token, org_id)
    _activate(client, token, org_id, workflow_id)

    trigger = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {}},
        headers=_auth_headers(token),
    )
    run_id = trigger.json()["id"]

    # A second, different graph becomes the new "current" version -- but the
    # run above was already created against version 1 before this happened.
    other_graph = {
        "nodes": [{"id": "start", "type": "trigger", "config": {}}],
        "edges": [],
    }
    client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/versions",
        json={"graph": other_graph},
        headers=_auth_headers(token),
    )

    await _run_synchronously(org_id, run_id)

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs/{run_id}",
        headers=_auth_headers(token),
    ).json()
    # Version 1's graph (start -> n1 -> n2) executed, not version 2's
    # (start only) -- proves the run's version was captured at creation.
    assert {step["node_id"] for step in detail["steps"]} == {"start", "n1", "n2"}


# --- durability: crash resumption ---


@pytest.mark.asyncio
async def test_resume_after_crash_does_not_redo_succeeded_steps_and_retakes_a_stuck_one(
    client: TestClient,
) -> None:
    token, org_id = _register_login_and_create_org(client)
    workflow_id = _create_workflow(client, token, org_id)
    _activate(client, token, org_id, workflow_id)

    trigger = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {}},
        headers=_auth_headers(token),
    )
    run_id = uuid.UUID(trigger.json()["id"])

    # Simulate a crash: node "start" already succeeded, node "n1" was
    # claimed ("running") and the worker died before finishing it, node
    # "n2" was never reached.
    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        run = await db.get(WorkflowRun, run_id)
        assert run is not None
        run.status = "running"
        db.add(
            StepRun(
                org_id=uuid.UUID(org_id),
                workflow_run_id=run_id,
                node_id="start",
                node_type="trigger",
                status="succeeded",
                attempts=1,
                input={},
                output={"type": "manual"},
            )
        )
        db.add(
            StepRun(
                org_id=uuid.UUID(org_id),
                workflow_run_id=run_id,
                node_id="n1",
                node_type="notify",
                status="running",
                attempts=1,
                input={"channel": "c1", "message": "step one"},
                output={},
            )
        )
        await db.commit()

    await _run_synchronously(org_id, str(run_id))

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs/{run_id}",
        headers=_auth_headers(token),
    ).json()
    assert detail["status"] == "completed"
    steps_by_node = {step["node_id"]: step for step in detail["steps"]}
    assert steps_by_node["start"]["attempts"] == 1  # untouched, not re-executed
    assert steps_by_node["n1"]["status"] == "succeeded"
    assert steps_by_node["n1"]["attempts"] == 2  # retaken: 1 (stuck) + 1 (resumed)
    assert steps_by_node["n2"]["status"] == "succeeded"


# --- idempotency ---


@pytest.mark.asyncio
async def test_reinvoking_a_completed_run_is_a_no_op(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    workflow_id = _create_workflow(client, token, org_id)
    _activate(client, token, org_id, workflow_id)

    trigger = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {}},
        headers=_auth_headers(token),
    )
    run_id = trigger.json()["id"]
    await _run_synchronously(org_id, run_id)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        before = (
            (await db.execute(select(StepRun).where(StepRun.workflow_run_id == uuid.UUID(run_id))))
            .scalars()
            .all()
        )
        before_count = len(before)

    await _run_synchronously(org_id, run_id)  # re-invoke a run that already finished

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        after = (
            (await db.execute(select(StepRun).where(StepRun.workflow_run_id == uuid.UUID(run_id))))
            .scalars()
            .all()
        )

    assert len(after) == before_count


@pytest.mark.asyncio
async def test_dispatching_the_same_event_twice_is_not_deduplicated_yet(client: TestClient) -> None:
    """Documents a known, accepted limitation (see workflows plan/§2): the
    fan-out from one DomainEvent to matching workflows has no per-(event,
    workflow) idempotency key, so a retried dispatch creates a second
    WorkflowRun rather than being deduplicated. Worst case is a duplicate
    run, never data corruption -- if this ever needs fixing, this test is
    the one to flip.
    """
    token, org_id = _register_login_and_create_org(client)
    graph = {
        "nodes": [{"id": "start", "type": "trigger", "config": {"event_type": "test.thing"}}],
        "edges": [],
    }
    workflow_id = _create_workflow(client, token, org_id, graph)
    _activate(client, token, org_id, workflow_id)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        event = await publish_event(db, uuid.UUID(org_id), "test.thing", {"k": "v"})

    async with session_factory() as db:
        await dispatch_domain_event_task({}, str(event.id), org_id)
    async with session_factory() as db:
        await dispatch_domain_event_task({}, str(event.id), org_id)

    runs = client.get(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs", headers=_auth_headers(token)
    ).json()
    assert len(runs) == 2


# --- event trigger end-to-end ---


async def _upload_and_ingest(client: TestClient, token: str, org_id: str, content: bytes) -> str:
    document_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("doc.txt", content, "text/plain")},
        headers=_auth_headers(token),
    ).json()["id"]
    async with session_factory() as db:
        await run_ingestion(db, uuid.UUID(org_id), uuid.UUID(document_id))
    return document_id


@pytest.mark.asyncio
async def test_document_ingested_event_triggers_a_matching_active_workflow(
    client: TestClient,
) -> None:
    token, org_id = _register_login_and_create_org(client)
    graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "config": {"event_type": "document.ingested"}}
        ],
        "edges": [],
    }
    workflow_id = _create_workflow(client, token, org_id, graph)
    _activate(client, token, org_id, workflow_id)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        event = await publish_event(
            db, uuid.UUID(org_id), "document.ingested", {"document_id": "irrelevant"}
        )

    await dispatch_domain_event_task({}, str(event.id), org_id)

    runs = client.get(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs", headers=_auth_headers(token)
    ).json()
    assert len(runs) == 1
    assert runs[0]["trigger"]["type"] == "event"


# --- webhook trigger ---


def test_webhook_trigger_requires_the_correct_secret(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    workflow_id = _create_workflow(client, token, org_id)
    _activate(client, token, org_id, workflow_id)
    workflow_detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}", headers=_auth_headers(token)
    ).json()
    secret = workflow_detail["webhook_secret"]
    assert secret  # exposed to workflows:manage callers so the webhook is actually usable

    wrong = client.post(
        f"/api/v1/webhooks/workflows/{org_id}/{workflow_id}",
        json={},
        headers={"X-Webhook-Secret": "wrong-secret"},
    )
    assert wrong.status_code == 401

    missing = client.post(f"/api/v1/webhooks/workflows/{org_id}/{workflow_id}", json={})
    assert missing.status_code == 422  # FastAPI: required header missing

    correct = client.post(
        f"/api/v1/webhooks/workflows/{org_id}/{workflow_id}",
        json={"k": "v"},
        headers={"X-Webhook-Secret": secret},
    )
    assert correct.status_code == 202
    assert correct.json()["trigger"]["type"] == "webhook"

    rotated = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/webhooks/rotate",
        headers=_auth_headers(token),
    ).json()
    assert rotated["webhook_secret"] != secret
    stale = client.post(
        f"/api/v1/webhooks/workflows/{org_id}/{workflow_id}",
        json={},
        headers={"X-Webhook-Secret": secret},
    )
    assert stale.status_code == 401


# --- retry / DLQ ---


@pytest.mark.asyncio
async def test_action_node_retries_then_dlqs_after_max_attempts(
    client: TestClient, monkeypatch
) -> None:
    call_count = {"n": 0}

    async def _always_fails(ctx: ToolContext, args: dict) -> dict:
        call_count["n"] += 1
        return {"error": "simulated failure"}

    monkeypatch.setitem(
        AGENT_TOOLS, "notify", Tool(spec=AGENT_TOOLS["notify"].spec, handler=_always_fails)
    )

    token, org_id = _register_login_and_create_org(client)
    graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "config": {}},
            {"id": "n1", "type": "action", "config": {"tool": "notify", "args": {}}},
        ],
        "edges": [{"from": "start", "to": "n1"}],
    }
    workflow_id = _create_workflow(client, token, org_id, graph)
    _activate(client, token, org_id, workflow_id)

    trigger = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {}},
        headers=_auth_headers(token),
    )
    run_id = uuid.UUID(trigger.json()["id"])
    max_attempts = get_settings().workflow_step_max_attempts

    for _ in range(max_attempts):
        await _run_synchronously(org_id, str(run_id))
        # Bypass the real backoff wait -- pull next_attempt_at into the past
        # so the following invocation treats it as due, same as a real
        # worker re-checking after the wait actually elapsed.
        async with session_factory() as db:
            await set_tenant_context(db, uuid.UUID(org_id))
            result = await db.execute(
                select(StepRun).where(StepRun.workflow_run_id == run_id, StepRun.node_id == "n1")
            )
            step = result.scalar_one_or_none()
            if step is not None and step.next_attempt_at is not None:
                step.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
                await db.commit()

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs/{run_id}",
        headers=_auth_headers(token),
    ).json()
    assert detail["status"] == "failed"
    n1 = next(step for step in detail["steps"] if step["node_id"] == "n1")
    assert n1["status"] == "dlq"
    assert n1["attempts"] == max_attempts
    assert call_count["n"] == max_attempts


@pytest.mark.asyncio
async def test_action_node_succeeds_on_second_attempt(client: TestClient, monkeypatch) -> None:
    call_count = {"n": 0}

    async def _fails_once(ctx: ToolContext, args: dict) -> dict:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"error": "transient failure"}
        return {"status": "recorded_not_delivered", "channel": "c", "message": "m"}

    monkeypatch.setitem(
        AGENT_TOOLS, "notify", Tool(spec=AGENT_TOOLS["notify"].spec, handler=_fails_once)
    )

    token, org_id = _register_login_and_create_org(client)
    graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "config": {}},
            {"id": "n1", "type": "action", "config": {"tool": "notify", "args": {}}},
        ],
        "edges": [{"from": "start", "to": "n1"}],
    }
    workflow_id = _create_workflow(client, token, org_id, graph)
    _activate(client, token, org_id, workflow_id)

    trigger = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {}},
        headers=_auth_headers(token),
    )
    run_id = uuid.UUID(trigger.json()["id"])

    await _run_synchronously(org_id, str(run_id))
    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        result = await db.execute(
            select(StepRun).where(StepRun.workflow_run_id == run_id, StepRun.node_id == "n1")
        )
        step = result.scalar_one()
        step.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()

    await _run_synchronously(org_id, str(run_id))

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs/{run_id}",
        headers=_auth_headers(token),
    ).json()
    assert detail["status"] == "completed"
    n1 = next(step for step in detail["steps"] if step["node_id"] == "n1")
    assert n1["status"] == "succeeded"
    assert n1["attempts"] == 2


# --- cost cap ---


@pytest.mark.asyncio
async def test_create_run_blocked_once_org_cost_cap_is_reached(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    graph = {
        "nodes": [
            {"id": "start", "type": "trigger", "config": {}},
            {
                "id": "ai1",
                "type": "ai",
                "config": {"instructions": "x", "allowed_tools": [], "input": "x"},
            },
        ],
        "edges": [{"from": "start", "to": "ai1"}],
    }
    workflow_id = _create_workflow(client, token, org_id, graph)
    _activate(client, token, org_id, workflow_id)

    client.put(
        f"{ORGS_PREFIX}/{org_id}/ai-config",
        json={"monthly_cost_cap_usd": 0.0001},
        headers=_auth_headers(token),
    )

    first = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {}},
        headers=_auth_headers(token),
    )
    assert first.status_code == 202
    await _run_synchronously(org_id, first.json()["id"])
    # Mocked usage (10 in / 5 out on claude-sonnet-5) costs
    # (10*2.0 + 5*10.0) / 1_000_000 = 0.00007 -- under 0.0001 the first time,
    # but WorkflowRun.cost accumulates, so run it twice to clear the cap.
    second = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {}},
        headers=_auth_headers(token),
    )
    assert second.status_code == 202
    await _run_synchronously(org_id, second.json()["id"])

    third = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows/{workflow_id}/runs",
        json={"input": {}},
        headers=_auth_headers(token),
    )
    assert third.status_code == 402
    assert third.json()["error"]["code"] == "quota_exceeded"
