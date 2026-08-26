import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import session_factory
from app.core.redis import get_redis_client
from app.main import app
from app.modules.documents import service as documents_service
from app.modules.ingestion.pipeline import run_ingestion
from app.modules.search.service import _decode_cursor, _encode_cursor, _reciprocal_rank_fusion

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


# --- unit: RRF fusion and cursor helpers, no DB involved ---


class _Hit:
    def __init__(self, id: uuid.UUID, document_id: uuid.UUID, ordinal: int) -> None:
        self.id = id
        self.document_id = document_id
        self.ordinal = ordinal


def test_reciprocal_rank_fusion_favors_hits_ranked_highly_in_both_lists() -> None:
    doc_id = uuid.uuid4()
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    lexical = [_Hit(a, doc_id, 0), _Hit(b, doc_id, 1), _Hit(c, doc_id, 2)]
    semantic = [_Hit(b, doc_id, 1), _Hit(c, doc_id, 2), _Hit(a, doc_id, 0)]

    fused = _reciprocal_rank_fusion(lexical, semantic)

    # b is #2 in lexical and #1 in semantic -> best combined rank.
    assert fused[0].chunk_id == b
    assert {hit.chunk_id for hit in fused} == {a, b, c}


def test_reciprocal_rank_fusion_deduplicates_chunks_present_in_both_lists() -> None:
    doc_id = uuid.uuid4()
    shared = uuid.uuid4()
    fused = _reciprocal_rank_fusion(
        [_Hit(shared, doc_id, 0)],
        [_Hit(shared, doc_id, 0)],
    )
    assert len(fused) == 1


def test_cursor_round_trips() -> None:
    assert _decode_cursor(_encode_cursor(42)) == 42


def test_decode_cursor_none_is_offset_zero() -> None:
    assert _decode_cursor(None) == 0


def test_decode_cursor_rejects_garbage() -> None:
    from app.core.errors import ValidationError

    with pytest.raises(ValidationError):
        _decode_cursor("not-a-valid-cursor!!")


# --- integration: real upload + ingest + search over a live DB ---


@pytest.mark.asyncio
async def test_search_finds_uploaded_document_by_keyword(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    await _upload_and_ingest(
        client, token, org_id, b"Helix supports hybrid search across the organization's documents."
    )

    response = client.get(
        f"{ORGS_PREFIX}/{org_id}/search",
        params={"q": "hybrid search"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) >= 1
    assert (
        "search" in body["results"][0]["snippet"].lower()
        or "hybrid" in body["results"][0]["snippet"].lower()
    )


@pytest.mark.asyncio
async def test_search_excludes_chunks_from_deleted_document(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    document_id = await _upload_and_ingest(
        client, token, org_id, b"This document mentions a very unique term: zylophant."
    )

    async with session_factory() as db:
        await documents_service.delete_document(db, uuid.UUID(org_id), uuid.UUID(document_id))

    response = client.get(
        f"{ORGS_PREFIX}/{org_id}/search",
        params={"q": "zylophant"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.asyncio
async def test_search_does_not_leak_across_tenants(client: TestClient) -> None:
    token_a, org_a = _register_login_and_create_org(client)
    token_b, org_b = _register_login_and_create_org(client)
    await _upload_and_ingest(
        client, token_a, org_a, b"Org A's confidential roadmap mentions project zephyrine."
    )

    response = client.get(
        f"{ORGS_PREFIX}/{org_b}/search",
        params={"q": "zephyrine"},
        headers=_auth_headers(token_b),
    )

    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.asyncio
async def test_search_paginates_without_duplicates(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    for i in range(3):
        await _upload_and_ingest(
            client,
            token,
            org_id,
            f"Document number {i} discusses quokka migration patterns.".encode(),
        )

    seen_chunk_ids: set[str] = set()
    cursor = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"q": "quokka", "limit": 1}
        if cursor:
            params["cursor"] = cursor
        response = client.get(
            f"{ORGS_PREFIX}/{org_id}/search", params=params, headers=_auth_headers(token)
        )
        body = response.json()
        assert len(body["results"]) <= 1
        for result in body["results"]:
            assert result["chunk_id"] not in seen_chunk_ids
            seen_chunk_ids.add(result["chunk_id"])
        cursor = body["next_cursor"]
        pages += 1
        if cursor is None or pages > 10:
            break

    assert len(seen_chunk_ids) == 3
