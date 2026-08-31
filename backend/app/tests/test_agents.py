import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.redis import get_redis_client
from app.main import app
from app.modules.agents import service as agents_service
from app.modules.agents.tools import TOOLS, ToolContext
from app.modules.ai import service as ai_service
from app.modules.ai.providers import ToolCall, ToolCompletionResult, UsageInfo
from app.modules.ingestion.pipeline import run_ingestion
from app.modules.orgs.system_roles import VIEWER_ROLE_ID

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
    # Same rationale as test_assistant.py/test_ai.py: never let a test call
    # a real provider. Default: one turn, no tool calls, a plain answer.
    # Individual tests override via monkeypatch when they need tool calls.
    async def _fake_complete_with_tools(
        system, messages, max_tokens, tools, *, provider=None, model=None
    ):
        return ToolCompletionResult(
            text="Final answer, no tools needed.",
            tool_calls=[],
            assistant_message={"role": "assistant", "content": "Final answer, no tools needed."},
            usage=UsageInfo(input_tokens=50, output_tokens=10),
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


async def _upload_and_ingest(client: TestClient, token: str, org_id: str, content: bytes) -> str:
    document_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("doc.txt", content, "text/plain")},
        headers=_auth_headers(token),
    ).json()["id"]
    async with session_factory() as db:
        await run_ingestion(db, uuid.UUID(org_id), uuid.UUID(document_id))
    return document_id


def _create_agent(
    client: TestClient,
    token: str,
    org_id: str,
    allowed_tools: list[str],
    instructions: str = "Help the user.",
) -> str:
    return client.post(
        f"{ORGS_PREFIX}/{org_id}/agents",
        json={"name": "Test Agent", "instructions": instructions, "allowed_tools": allowed_tools},
        headers=_auth_headers(token),
    ).json()["id"]


async def _run_synchronously(org_id: str, run_id: str) -> None:
    # Mirrors _upload_and_ingest's pattern for ingestion: the real API call
    # enqueues to Redis (a real queue, harmless with no worker consuming it
    # in tests), and the test runs the worker's actual logic inline against
    # its own session, exactly like the worker task would.
    async with session_factory() as db:
        await agents_service.execute_run(db, uuid.UUID(org_id), uuid.UUID(run_id))


# --- unit: individual tool handlers ---


@pytest.mark.asyncio
async def test_notify_tool_delivers_per_recipient_preferences(client: TestClient) -> None:
    # Phase 15: the notify tool delivers for real via the notifications
    # module, fanning out across whichever channels the recipient (the
    # user who triggered the run, by default) has enabled.
    token, org_id = _register_login_and_create_org(client)
    user_id = uuid.UUID(client.get(f"{AUTH_PREFIX}/me", headers=_auth_headers(token)).json()["id"])

    async with session_factory() as db:
        ctx = ToolContext(db=db, org_id=uuid.UUID(org_id), user_id=user_id)
        result = await TOOLS["notify"].handler(ctx, {"message": "hi"})

    assert result["status"] == "queued"
    assert len(result["notification_ids"]) == 2  # email + in_app, both enabled by default

    inbox = client.get(f"{ORGS_PREFIX}/{org_id}/notifications", headers=_auth_headers(token)).json()
    assert any(n["body"] == "hi" for n in inbox["results"])


@pytest.mark.asyncio
async def test_notify_tool_returns_error_for_non_member_recipient() -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as db:
        ctx = ToolContext(db=db, org_id=org_id, user_id=user_id)
        result = await TOOLS["notify"].handler(ctx, {"message": "hi"})

    assert "error" in result


@pytest.mark.asyncio
async def test_http_request_tool_denies_by_default() -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as db:
        ctx = ToolContext(db=db, org_id=org_id, user_id=user_id)
        result = await TOOLS["http_request"].handler(ctx, {"url": "https://example.com/data"})

    assert "not on the http_request allowlist" in result["error"]


@pytest.mark.asyncio
async def test_http_request_tool_allows_allowlisted_host(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_http_allowlist", ["example.com"])

    class _FakeResponse:
        status_code = 200
        text = "ok"

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, method, url, content=None):
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=10.0: _FakeClient())

    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as db:
        ctx = ToolContext(db=db, org_id=org_id, user_id=user_id)
        result = await TOOLS["http_request"].handler(ctx, {"url": "https://example.com/data"})

    assert result == {"status_code": 200, "body": "ok"}


@pytest.mark.asyncio
async def test_fetch_document_tool_returns_content(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    document_id = await _upload_and_ingest(
        client, token, org_id, b"The agents module wraps existing services."
    )

    async with session_factory() as db:
        ctx = ToolContext(db=db, org_id=uuid.UUID(org_id), user_id=uuid.uuid4())
        result = await TOOLS["fetch_document"].handler(ctx, {"document_id": document_id})

    assert result["title"] == "doc.txt"
    assert "agents module" in result["content"]


@pytest.mark.asyncio
async def test_fetch_document_tool_unknown_id_returns_error() -> None:
    async with session_factory() as db:
        ctx = ToolContext(db=db, org_id=uuid.uuid4(), user_id=uuid.uuid4())
        result = await TOOLS["fetch_document"].handler(ctx, {"document_id": str(uuid.uuid4())})

    assert result == {"error": "document not found"}


@pytest.mark.asyncio
async def test_search_tool_finds_ingested_content(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    await _upload_and_ingest(client, token, org_id, b"Helix agents can call the search tool.")
    user_id = uuid.UUID(client.get(f"{AUTH_PREFIX}/me", headers=_auth_headers(token)).json()["id"])

    async with session_factory() as db:
        ctx = ToolContext(db=db, org_id=uuid.UUID(org_id), user_id=user_id)
        result = await TOOLS["search"].handler(ctx, {"query": "search tool"})

    assert len(result["results"]) >= 1
    assert (
        "agents" in result["results"][0]["snippet"].lower()
        or "search" in result["results"][0]["snippet"].lower()
    )


# --- integration: agent CRUD + permission checks ---


def test_create_agent_rejects_unknown_tool(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)

    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/agents",
        json={"name": "Bad Agent", "instructions": "x", "allowed_tools": ["not_a_real_tool"]},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422


def test_create_and_list_agents(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    _create_agent(client, token, org_id, ["search"])

    agents = client.get(f"{ORGS_PREFIX}/{org_id}/agents", headers=_auth_headers(token)).json()
    assert len(agents) == 1
    assert agents[0]["allowed_tools"] == ["search"]


def test_viewer_cannot_create_agent(client: TestClient) -> None:
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
        f"{ORGS_PREFIX}/{org_id}/agents",
        json={"name": "Agent", "instructions": "x", "allowed_tools": []},
        headers=_auth_headers(viewer_token),
    )
    assert response.status_code == 403


# --- integration: run lifecycle, guardrails ---


@pytest.mark.asyncio
async def test_run_with_no_tool_calls_completes_immediately(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    agent_id = _create_agent(client, token, org_id, [])

    trigger = client.post(
        f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs",
        json={"input": "Just answer directly."},
        headers=_auth_headers(token),
    )
    assert trigger.status_code == 202
    run_id = trigger.json()["id"]
    assert trigger.json()["status"] == "pending"

    await _run_synchronously(org_id, run_id)

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs/{run_id}", headers=_auth_headers(token)
    ).json()
    assert detail["status"] == "completed"
    assert detail["output"] == "Final answer, no tools needed."
    assert len(detail["steps"]) == 1
    assert detail["steps"][0]["type"] == "final_answer"
    assert detail["tokens"] == 60


@pytest.mark.asyncio
async def test_run_calls_allowed_tool_then_completes(client: TestClient, monkeypatch) -> None:
    token, org_id = _register_login_and_create_org(client)
    agent_id = _create_agent(client, token, org_id, ["notify"])

    call_count = {"n": 0}

    async def _fake(system, messages, max_tokens, tools, *, provider=None, model=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ToolCompletionResult(
                text="",
                tool_calls=[
                    ToolCall(
                        id="call_1", name="notify", arguments={"channel": "email", "message": "hi"}
                    )
                ],
                assistant_message={"role": "assistant", "content": "calling notify"},
                usage=UsageInfo(input_tokens=40, output_tokens=8),
            )
        return ToolCompletionResult(
            text="Notified.",
            tool_calls=[],
            assistant_message={"role": "assistant", "content": "Notified."},
            usage=UsageInfo(input_tokens=20, output_tokens=4),
        )

    monkeypatch.setattr(ai_service, "complete_with_tools", _fake)

    run_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs",
        json={"input": "Notify someone."},
        headers=_auth_headers(token),
    ).json()["id"]

    await _run_synchronously(org_id, run_id)

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs/{run_id}", headers=_auth_headers(token)
    ).json()
    assert detail["status"] == "completed"
    assert detail["output"] == "Notified."
    step_types = [step["type"] for step in detail["steps"]]
    assert step_types == ["tool_call", "final_answer"]
    assert detail["steps"][0]["tool"] == "notify"
    assert detail["steps"][0]["output"]["status"] == "queued"


@pytest.mark.asyncio
async def test_run_refuses_tool_not_in_agents_allowed_list(client: TestClient, monkeypatch) -> None:
    token, org_id = _register_login_and_create_org(client)
    # Agent is only allowed "search" — the model asks for "http_request" anyway.
    agent_id = _create_agent(client, token, org_id, ["search"])

    call_count = {"n": 0}

    async def _fake(system, messages, max_tokens, tools, *, provider=None, model=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ToolCompletionResult(
                text="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="http_request",
                        arguments={"url": "https://evil.example.com"},
                    )
                ],
                assistant_message={"role": "assistant", "content": "calling http_request"},
                usage=UsageInfo(input_tokens=40, output_tokens=8),
            )
        return ToolCompletionResult(
            text="Gave up.",
            tool_calls=[],
            assistant_message={"role": "assistant", "content": "Gave up."},
            usage=UsageInfo(input_tokens=10, output_tokens=4),
        )

    monkeypatch.setattr(ai_service, "complete_with_tools", _fake)

    run_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs",
        json={"input": "Try something sneaky."},
        headers=_auth_headers(token),
    ).json()["id"]

    await _run_synchronously(org_id, run_id)

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs/{run_id}", headers=_auth_headers(token)
    ).json()
    # The guardrail is enforced server-side, not just by which tools were
    # offered in the prompt — a model asking for a disallowed tool anyway
    # gets a recorded refusal, not an executed http_request.
    assert detail["steps"][0]["tool"] == "http_request"
    assert "not allowed for this agent" in detail["steps"][0]["output"]["error"]


@pytest.mark.asyncio
async def test_run_fails_after_max_steps_when_model_never_stops(
    client: TestClient, monkeypatch
) -> None:
    token, org_id = _register_login_and_create_org(client)
    agent_id = _create_agent(client, token, org_id, ["notify"])
    monkeypatch.setattr(get_settings(), "agent_max_steps", 2)

    async def _always_calls_tool(system, messages, max_tokens, tools, *, provider=None, model=None):
        return ToolCompletionResult(
            text="",
            tool_calls=[
                ToolCall(
                    id=str(uuid.uuid4()), name="notify", arguments={"channel": "x", "message": "y"}
                )
            ],
            assistant_message={"role": "assistant", "content": "still going"},
            usage=UsageInfo(input_tokens=10, output_tokens=2),
        )

    monkeypatch.setattr(ai_service, "complete_with_tools", _always_calls_tool)

    run_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs",
        json={"input": "Loop forever."},
        headers=_auth_headers(token),
    ).json()["id"]

    await _run_synchronously(org_id, run_id)

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs/{run_id}", headers=_auth_headers(token)
    ).json()
    assert detail["status"] == "failed"
    assert "maximum step count" in detail["error"]
    assert len(detail["steps"]) == 2  # exactly agent_max_steps tool_call steps, no final_answer


# --- integration: org-level cost cap blocks enqueuing a new run ---


@pytest.mark.asyncio
async def test_create_run_blocked_once_org_cost_cap_is_reached(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    agent_id = _create_agent(client, token, org_id, [])

    client.put(
        f"{ORGS_PREFIX}/{org_id}/ai-config",
        json={"monthly_cost_cap_usd": 0.0001},
        headers=_auth_headers(token),
    )

    first = client.post(
        f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs",
        json={"input": "hello"},
        headers=_auth_headers(token),
    )
    assert first.status_code == 202
    await _run_synchronously(org_id, first.json()["id"])
    # The default mock's usage (50 in / 10 out on claude-sonnet-5) costs
    # (50*2.0 + 10*10.0) / 1_000_000 = 0.0002, already over the 0.0001 cap.

    second = client.post(
        f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs",
        json={"input": "hello again"},
        headers=_auth_headers(token),
    )
    assert second.status_code == 402
    assert second.json()["error"]["code"] == "quota_exceeded"


# --- per-user rate limit on starting a run (Phase 19, SPEC.md §29) ---


def test_trigger_run_rate_limited_per_user(client: TestClient, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_run_rate_limit_max_requests", 2)
    token, org_id = _register_login_and_create_org(client)
    agent_id = _create_agent(client, token, org_id, [])

    responses = [
        client.post(
            f"{ORGS_PREFIX}/{org_id}/agents/{agent_id}/runs",
            json={"input": "hello"},
            headers=_auth_headers(token),
        )
        for _ in range(3)
    ]

    assert [r.status_code for r in responses[:2]] == [202, 202]
    assert responses[2].status_code == 429
    assert responses[2].json()["error"]["code"] == "rate_limited"
