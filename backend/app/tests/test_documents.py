import asyncio
import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.redis import get_redis_client
from app.core.storage import get_s3_client
from app.core.tenancy import set_tenant_context
from app.main import app
from app.modules.documents import service as documents_service
from app.modules.documents.models import Document, DocumentACL, Source
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


def _unique_email() -> str:
    return f"user-{uuid.uuid4()}@example.com"


def _register_login_and_create_org(client: TestClient) -> tuple[str, str]:
    """Returns (access_token, org_id) for a fresh Owner of a fresh org."""
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


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_upload_then_list_then_get(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    content = b"hello helix, this is a test document"

    upload_response = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("hello.txt", content, "text/plain")},
        headers=_auth_headers(token),
    )
    assert upload_response.status_code == 201
    body = upload_response.json()
    assert body["title"] == "hello.txt"
    assert body["mime"] == "text/plain"
    assert body["status"] == "pending"
    assert body["checksum"] == hashlib.sha256(content).hexdigest()
    document_id = body["id"]

    list_response = client.get(f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token))
    assert list_response.status_code == 200
    assert any(d["id"] == document_id for d in list_response.json())

    get_response = client.get(
        f"{ORGS_PREFIX}/{org_id}/documents/{document_id}", headers=_auth_headers(token)
    )
    assert get_response.status_code == 200
    assert get_response.json()["id"] == document_id


def test_uploaded_file_is_actually_in_object_storage(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    content = b"verify this exact content made it into minio"

    upload_response = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("proof.txt", content, "text/plain")},
        headers=_auth_headers(token),
    )
    document_id = upload_response.json()["id"]
    expected_key = f"{org_id}/{document_id}/proof.txt"

    settings = get_settings()
    s3 = get_s3_client()
    stored = s3.get_object(Bucket=settings.s3_bucket, Key=expected_key)
    assert stored["Body"].read() == content


@pytest.mark.asyncio
async def test_upload_creates_org_wide_acl(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    document_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("f.txt", b"content", "text/plain")},
        headers=_auth_headers(token),
    ).json()["id"]

    async with session_factory() as session:
        await set_tenant_context(session, uuid.UUID(org_id))
        result = await session.execute(
            select(DocumentACL).where(DocumentACL.document_id == uuid.UUID(document_id))
        )
        acls = list(result.scalars().all())

    assert len(acls) == 1
    assert acls[0].principal_type == "org"
    assert acls[0].principal_id == uuid.UUID(org_id)


@pytest.mark.asyncio
async def test_get_or_create_manual_source_survives_a_concurrent_race(client: TestClient) -> None:
    # Regression test (Phase 20, migration 11400a085f70): two concurrent
    # first-uploads to the same brand-new org used to race
    # get_or_create_manual_source's check-then-insert and raise
    # sqlalchemy.exc.MultipleResultsFound on every request after -- found
    # via a real k6 load test (infra/load/ingestion.js), not by an
    # automated test, which is exactly why this one exists now.
    token, org_id = _register_login_and_create_org(client)

    async def _get_or_create() -> uuid.UUID:
        async with session_factory() as session:
            await set_tenant_context(session, uuid.UUID(org_id))
            source = await documents_service.get_or_create_manual_source(session, uuid.UUID(org_id))
            await session.commit()
            return source.id

    results = await asyncio.gather(_get_or_create(), _get_or_create())
    assert results[0] == results[1]

    async with session_factory() as session:
        await set_tenant_context(session, uuid.UUID(org_id))
        result = await session.execute(
            select(Source).where(
                Source.org_id == uuid.UUID(org_id),
                Source.type == "manual",
                Source.deleted_at.is_(None),
            )
        )
        assert len(list(result.scalars().all())) == 1


def test_delete_is_soft_and_hides_from_listing(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    document_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("to-delete.txt", b"bye", "text/plain")},
        headers=_auth_headers(token),
    ).json()["id"]

    delete_response = client.delete(
        f"{ORGS_PREFIX}/{org_id}/documents/{document_id}", headers=_auth_headers(token)
    )
    assert delete_response.status_code == 204

    list_response = client.get(f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token))
    assert all(d["id"] != document_id for d in list_response.json())

    get_response = client.get(
        f"{ORGS_PREFIX}/{org_id}/documents/{document_id}", headers=_auth_headers(token)
    )
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_soft_deleted_document_row_still_exists(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    document_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("still-here.txt", b"data", "text/plain")},
        headers=_auth_headers(token),
    ).json()["id"]

    client.delete(f"{ORGS_PREFIX}/{org_id}/documents/{document_id}", headers=_auth_headers(token))

    async with session_factory() as session:
        await set_tenant_context(session, uuid.UUID(org_id))
        document = await session.get(Document, uuid.UUID(document_id))
        assert document is not None
        assert document.deleted_at is not None


def test_tenant_isolation_across_orgs() -> None:
    with (
        TestClient(app, base_url="https://testserver") as client_a,
        TestClient(app, base_url="https://testserver") as client_b,
    ):
        token_a, org_a_id = _register_login_and_create_org(client_a)
        token_b, org_b_id = _register_login_and_create_org(client_b)

        document_id = client_a.post(
            f"{ORGS_PREFIX}/{org_a_id}/documents",
            files={"file": ("secret.txt", b"private to org a", "text/plain")},
            headers=_auth_headers(token_a),
        ).json()["id"]

        cross_org_get = client_b.get(
            f"{ORGS_PREFIX}/{org_a_id}/documents/{document_id}", headers=_auth_headers(token_b)
        )
        assert cross_org_get.status_code == 404

        cross_org_list = client_b.get(
            f"{ORGS_PREFIX}/{org_a_id}/documents", headers=_auth_headers(token_b)
        )
        assert cross_org_list.status_code == 404


def test_viewer_can_list_but_not_upload() -> None:
    with (
        TestClient(app, base_url="https://testserver") as client_a,
        TestClient(app, base_url="https://testserver") as client_b,
    ):
        email_b, token_a, token_b, org_id = _owner_and_second_member(client_a, client_b)
        membership_id_b = _membership_id_for(client_a, token_a, org_id, email_b)

        promote = client_a.put(
            f"{ORGS_PREFIX}/{org_id}/memberships/{membership_id_b}/role",
            json={"role_id": str(VIEWER_ROLE_ID)},
            headers=_auth_headers(token_a),
        )
        assert promote.status_code == 200

        list_response = client_b.get(
            f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token_b)
        )
        assert list_response.status_code == 200

        upload_response = client_b.post(
            f"{ORGS_PREFIX}/{org_id}/documents",
            files={"file": ("nope.txt", b"nope", "text/plain")},
            headers=_auth_headers(token_b),
        )
        assert upload_response.status_code == 403


def _owner_and_second_member(
    client_a: TestClient, client_b: TestClient
) -> tuple[str, str, str, str]:
    token_a, org_id = _register_login_and_create_org(client_a)
    email_b = _unique_email()
    password_b = "a-strong-password-1"
    client_b.post(f"{AUTH_PREFIX}/register", json={"email": email_b, "password": password_b})
    token_b = client_b.post(
        f"{AUTH_PREFIX}/login", json={"email": email_b, "password": password_b}
    ).json()["access_token"]

    raw_token = client_a.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": email_b},
        headers=_auth_headers(token_a),
    ).json()["token"]
    accept_response = client_b.post(
        f"/api/v1/invitations/{raw_token}/accept", headers=_auth_headers(token_b)
    )
    token_b = accept_response.json()["access_token"]
    return email_b, token_a, token_b, org_id


def _membership_id_for(client: TestClient, token: str, org_id: str, email: str) -> str:
    members = client.get(f"{ORGS_PREFIX}/{org_id}/members", headers=_auth_headers(token)).json()
    return next(m["id"] for m in members if m["email"] == email)
