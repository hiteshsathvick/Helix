import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import session_factory
from app.core.errors import ValidationError
from app.core.redis import get_redis_client
from app.core.tenancy import set_tenant_context
from app.main import app
from app.modules.documents.models import Document
from app.modules.ingestion.chunking import chunk_text
from app.modules.ingestion.embeddings import embed_texts
from app.modules.ingestion.extraction import extract_text
from app.modules.ingestion.models import EMBEDDING_DIMENSIONS, Chunk, Job
from app.modules.ingestion.pipeline import run_ingestion
from app.modules.ingestion.tasks import ingest_document_task

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


# --- pipeline unit tests, no worker involved ---


def test_extract_text_plain() -> None:
    assert extract_text(b"hello world", "text/plain") == "hello world"


def test_extract_text_html_strips_tags() -> None:
    html = b"<html><body><h1>Title</h1><p>Body text</p></body></html>"
    extracted = extract_text(html, "text/html")
    assert "Title" in extracted
    assert "Body text" in extracted
    assert "<h1>" not in extracted


def test_extract_text_unsupported_mime_raises() -> None:
    with pytest.raises(ValidationError):
        extract_text(b"whatever", "application/zip")


def test_chunk_text_respects_overlap_and_size() -> None:
    text = " ".join(f"word{i}" for i in range(2000))
    chunks = chunk_text(text, chunk_tokens=800, overlap_tokens=100)
    assert len(chunks) > 1

    from app.modules.ingestion.chunking import _encoding

    first_tokens = _encoding.encode(chunks[0])
    second_tokens = _encoding.encode(chunks[1])
    assert len(first_tokens) <= 800
    # The last 100 tokens of chunk 0 are exactly the first 100 of chunk 1 —
    # that's what "overlap_tokens=100" means.
    assert first_tokens[-100:] == second_tokens[:100]


def test_chunk_text_empty_string_returns_no_chunks() -> None:
    assert chunk_text("", chunk_tokens=800, overlap_tokens=100) == []


def test_embed_texts_returns_correct_dimensions_and_is_deterministic() -> None:
    vectors = embed_texts(["the quick brown fox", "the quick brown fox"])
    assert len(vectors) == 2
    assert len(vectors[0]) == EMBEDDING_DIMENSIONS
    assert vectors[0] == vectors[1]


def test_embed_texts_empty_list_returns_empty() -> None:
    assert embed_texts([]) == []


# --- pipeline integration: real upload, real pgvector/FTS storage ---


@pytest.mark.asyncio
async def test_run_ingestion_creates_chunks_with_embeddings_and_acl_hash(
    client: TestClient,
) -> None:
    token, org_id = _register_login_and_create_org(client)
    content = b"Helix is a multi-tenant AI platform. " * 50
    document_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("doc.txt", content, "text/plain")},
        headers=_auth_headers(token),
    ).json()["id"]

    async with session_factory() as db:
        chunk_count = await run_ingestion(db, uuid.UUID(org_id), uuid.UUID(document_id))
        assert chunk_count > 0

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        result = await db.execute(select(Chunk).where(Chunk.document_id == uuid.UUID(document_id)))
        chunks = list(result.scalars().all())

    assert len(chunks) == chunk_count
    assert all(c.embedding is not None and len(c.embedding) == EMBEDDING_DIMENSIONS for c in chunks)
    assert all(c.acl_hash == chunks[0].acl_hash for c in chunks)
    assert all(c.ordinal == i for i, c in enumerate(sorted(chunks, key=lambda c: c.ordinal)))


@pytest.mark.asyncio
async def test_run_ingestion_is_idempotent_on_reindex(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    document_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("doc.txt", b"short content", "text/plain")},
        headers=_auth_headers(token),
    ).json()["id"]

    async with session_factory() as db:
        first_count = await run_ingestion(db, uuid.UUID(org_id), uuid.UUID(document_id))
    async with session_factory() as db:
        second_count = await run_ingestion(db, uuid.UUID(org_id), uuid.UUID(document_id))

    assert first_count == second_count

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        result = await db.execute(select(Chunk).where(Chunk.document_id == uuid.UUID(document_id)))
        # Re-running must replace, not duplicate.
        assert len(list(result.scalars().all())) == first_count


# --- the arq task: retries, DLQ, and the full async path via a real upload ---


@pytest.mark.asyncio
async def test_ingest_document_task_marks_document_indexed(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    document_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("doc.txt", b"content to embed", "text/plain")},
        headers=_auth_headers(token),
    ).json()["id"]

    job_id = client.get(
        f"{ORGS_PREFIX}/{org_id}/documents/{document_id}/ingestion", headers=_auth_headers(token)
    ).json()["id"]

    await ingest_document_task({"job_try": 1}, job_id, org_id, document_id)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        document = await db.get(Document, uuid.UUID(document_id))
        assert document is not None
        assert document.status == "indexed"

        job = await db.get(Job, uuid.UUID(job_id))
        assert job is not None
        assert job.status == "succeeded"
        assert job.attempts == 1


@pytest.mark.asyncio
async def test_ingest_document_task_dlqs_after_max_attempts(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    # An unsupported mime type makes extract_text fail deterministically.
    document_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("doc.zip", b"not really a zip", "application/zip")},
        headers=_auth_headers(token),
    ).json()["id"]

    job_id = client.get(
        f"{ORGS_PREFIX}/{org_id}/documents/{document_id}/ingestion", headers=_auth_headers(token)
    ).json()["id"]

    for attempt in (1, 2, 3):
        with pytest.raises(ValidationError):
            await ingest_document_task({"job_try": attempt}, job_id, org_id, document_id)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        job = await db.get(Job, uuid.UUID(job_id))
        assert job is not None
        assert job.status == "dlq"
        assert job.attempts == 3
        assert job.error is not None

        document = await db.get(Document, uuid.UUID(document_id))
        assert document is not None
        assert document.status == "failed"
