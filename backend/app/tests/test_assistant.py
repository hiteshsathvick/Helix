import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import session_factory
from app.core.redis import get_redis_client
from app.main import app
from app.modules.ai import service as ai_service
from app.modules.assistant.service import _assemble_context, _title_from_query
from app.modules.ingestion.pipeline import run_ingestion
from app.modules.search.schemas import SearchResult

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


async def _fake_stream_completion(system, messages, max_tokens, *, provider=None, model=None):
    yield ai_service.TextDelta("Test answer ")
    yield ai_service.TextDelta("from mock.")
    yield ai_service.UsageInfo(input_tokens=100, output_tokens=20)


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    # Automated tests must never call the real Anthropic API — it costs
    # real money and would make CI nondeterministic. Every test in this
    # file gets the mock; a real-API smoke check (if ever wanted) belongs
    # in a manual/opt-in script, not here.
    monkeypatch.setattr(ai_service, "stream_completion", _fake_stream_completion)


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


def _parse_sse_events(response_text: str) -> list[dict]:
    events = []
    for line in response_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


# --- unit: context assembly and title truncation, no DB involved ---


def _search_result(chunk_id: uuid.UUID, document_id: uuid.UUID, title: str) -> SearchResult:
    return SearchResult(
        document_id=document_id,
        document_title=title,
        chunk_id=chunk_id,
        ordinal=0,
        snippet="a snippet",
        score=1.0,
    )


def test_assemble_context_respects_token_budget() -> None:
    doc_id = uuid.uuid4()
    results = [_search_result(uuid.uuid4(), doc_id, "Doc") for _ in range(5)]
    contents = {r.chunk_id: "word " * 500 for r in results}  # each ~500+ tokens

    context, used = _assemble_context(results, contents, token_budget=600)

    assert len(used) < len(results)
    assert len(used) >= 1


def test_assemble_context_keeps_at_least_one_chunk_even_if_over_budget() -> None:
    doc_id = uuid.uuid4()
    results = [_search_result(uuid.uuid4(), doc_id, "Doc")]
    contents = {results[0].chunk_id: "word " * 10000}

    context, used = _assemble_context(results, contents, token_budget=10)

    assert len(used) == 1


def test_assemble_context_with_no_results_uses_placeholder() -> None:
    context, used = _assemble_context([], {}, token_budget=1000)
    assert used == []
    assert "No relevant documents" in context


def test_title_from_query_truncates_long_queries() -> None:
    long_query = "a" * 100
    title = _title_from_query(long_query)
    assert len(title) == 60
    assert title.endswith("...")


def test_title_from_query_keeps_short_queries_as_is() -> None:
    assert _title_from_query("short question") == "short question"


# --- integration: real upload + ingest + assistant query, mocked LLM ---


@pytest.mark.asyncio
async def test_assistant_query_streams_and_persists(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    await _upload_and_ingest(
        client, token, org_id, b"Helix supports a RAG assistant with streaming and citations."
    )

    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/assistant/query",
        json={"query": "What does Helix support?"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    token_events = [e for e in events if e["type"] == "token"]
    done_events = [e for e in events if e["type"] == "done"]

    assert "".join(e["text"] for e in token_events) == "Test answer from mock."
    assert len(done_events) == 1
    assert len(done_events[0]["citations"]) >= 1

    # persisted: a conversation with both the user and assistant message
    conversations = client.get(
        f"{ORGS_PREFIX}/{org_id}/conversations", headers=_auth_headers(token)
    ).json()
    assert len(conversations) == 1
    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/conversations/{conversations[0]['id']}",
        headers=_auth_headers(token),
    ).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant"]
    assert detail["messages"][1]["content"] == "Test answer from mock."
    assert detail["messages"][1]["tokens"] == 120


@pytest.mark.asyncio
async def test_assistant_query_reuses_existing_conversation(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    await _upload_and_ingest(client, token, org_id, b"Some document content about widgets.")

    first = client.post(
        f"{ORGS_PREFIX}/{org_id}/assistant/query",
        json={"query": "Tell me about widgets"},
        headers=_auth_headers(token),
    )
    done_event = [e for e in _parse_sse_events(first.text) if e["type"] == "done"][0]
    conversation_id = done_event["conversation_id"]

    client.post(
        f"{ORGS_PREFIX}/{org_id}/assistant/query",
        json={"query": "Tell me more", "conversation_id": conversation_id},
        headers=_auth_headers(token),
    )

    detail = client.get(
        f"{ORGS_PREFIX}/{org_id}/conversations/{conversation_id}", headers=_auth_headers(token)
    ).json()
    assert len(detail["messages"]) == 4  # 2 user + 2 assistant turns in one conversation

    all_conversations = client.get(
        f"{ORGS_PREFIX}/{org_id}/conversations", headers=_auth_headers(token)
    ).json()
    assert len(all_conversations) == 1


@pytest.mark.asyncio
async def test_assistant_query_unknown_conversation_id_404s(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)

    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/assistant/query",
        json={"query": "hi", "conversation_id": str(uuid.uuid4())},
        headers=_auth_headers(token),
    )

    # Conversation ownership is resolved *before* the SSE stream opens
    # (router.py), so an invalid conversation_id is a normal 404 — not a
    # broken/partial stream.
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_assistant_does_not_leak_citations_across_tenants(client: TestClient) -> None:
    token_a, org_a = _register_login_and_create_org(client)
    token_b, org_b = _register_login_and_create_org(client)
    await _upload_and_ingest(
        client, token_a, org_a, b"Org A's confidential roadmap mentions project zephyrine."
    )

    response = client.post(
        f"{ORGS_PREFIX}/{org_b}/assistant/query",
        json={"query": "Tell me about project zephyrine"},
        headers=_auth_headers(token_b),
    )

    events = _parse_sse_events(response.text)
    done = [e for e in events if e["type"] == "done"][0]
    assert done["citations"] == []
