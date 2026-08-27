import urllib.parse
import uuid
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.redis import get_redis_client
from app.core.tenancy import set_tenant_context
from app.main import app
from app.modules.connectors import service as connectors_service
from app.modules.connectors.crypto import decrypt_token, encrypt_token
from app.modules.documents import service as documents_service
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
def _web_allowlist(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "connector_web_allowlist", ["docs.example.com"])


@pytest.fixture(autouse=True)
def _github_oauth_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "github_oauth_client_id", "test-client-id")
    monkeypatch.setattr(settings, "github_oauth_client_secret", "test-client-secret")


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


class _FakeResponse:
    def __init__(
        self, status_code: int = 200, json_data: Any = None, content: bytes = b"", headers=None
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = content.decode() if isinstance(content, bytes) else content
        self.headers = headers or {}

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)  # type: ignore[arg-type]


class _FakeClient:
    def __init__(self, responder, **kwargs) -> None:
        self._responder = responder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs) -> _FakeResponse:
        return self._responder("GET", url, kwargs)

    async def post(self, url, **kwargs) -> _FakeResponse:
        return self._responder("POST", url, kwargs)

    async def head(self, url, **kwargs) -> _FakeResponse:
        return self._responder("HEAD", url, kwargs)


def _mock_http(monkeypatch, responder) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeClient(responder, **kwargs))


async def _run_sync(org_id: str, source_id: str) -> None:
    async with session_factory() as db:
        await connectors_service.run_sync(db, uuid.UUID(org_id), uuid.UUID(source_id))


def _create_web_connector(client: TestClient, token: str, org_id: str, urls: list[str]) -> str:
    return client.post(
        f"{ORGS_PREFIX}/{org_id}/connectors",
        json={"name": "Docs site", "url_list": urls},
        headers=_auth_headers(token),
    ).json()["id"]


# --- encryption ---


def test_encrypt_decrypt_token_round_trips():
    plaintext = "gho_super-secret-token-value"
    ciphertext = encrypt_token(plaintext)
    assert ciphertext != plaintext
    assert decrypt_token(ciphertext) == plaintext


# --- web connector: allowlist ---


def test_create_web_connector_rejects_disallowed_host(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/connectors",
        json={"name": "Bad", "url_list": ["https://not-allowed.example.com/page"]},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422


def test_create_web_connector_allows_allowlisted_host(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/connectors",
        json={"name": "Good", "url_list": ["https://docs.example.com/page"]},
        headers=_auth_headers(token),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "active"


# --- web connector: sync idempotency / incremental updates / ACL mapping ---


@pytest.mark.asyncio
async def test_web_connector_sync_creates_documents_with_org_acl(
    client: TestClient, monkeypatch
) -> None:
    urls = ["https://docs.example.com/a", "https://docs.example.com/b"]

    def responder(method, url, kwargs):
        if method == "HEAD":
            return _FakeResponse(status_code=200, headers={"etag": f'"{url}-v1"'})
        return _FakeResponse(status_code=200, content=f"content of {url}".encode(), headers={})

    _mock_http(monkeypatch, responder)

    token, org_id = _register_login_and_create_org(client)
    source_id = _create_web_connector(client, token, org_id, urls)

    await _run_sync(org_id, source_id)

    documents = client.get(f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token)).json()
    assert len(documents) == 2

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        for document in documents:
            principals = await documents_service.get_document_acl_principals(
                db, uuid.UUID(org_id), uuid.UUID(document["id"])
            )
            assert principals == [("org", uuid.UUID(org_id))]

    connector = client.get(
        f"{ORGS_PREFIX}/{org_id}/connectors/{source_id}", headers=_auth_headers(token)
    ).json()
    assert connector["status"] == "active"
    assert connector["last_synced_at"] is not None


@pytest.mark.asyncio
async def test_web_connector_resync_with_no_changes_writes_nothing(
    client: TestClient, monkeypatch
) -> None:
    urls = ["https://docs.example.com/a"]
    fetch_count = {"n": 0}

    def responder(method, url, kwargs):
        if method == "HEAD":
            return _FakeResponse(status_code=200, headers={"etag": '"stable"'})
        fetch_count["n"] += 1
        return _FakeResponse(status_code=200, content=b"stable content")

    _mock_http(monkeypatch, responder)

    token, org_id = _register_login_and_create_org(client)
    source_id = _create_web_connector(client, token, org_id, urls)

    await _run_sync(org_id, source_id)
    first_count = fetch_count["n"]
    documents_after_first = client.get(
        f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token)
    ).json()

    await _run_sync(org_id, source_id)
    documents_after_second = client.get(
        f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token)
    ).json()

    assert len(documents_after_first) == len(documents_after_second) == 1
    assert documents_after_first[0]["checksum"] == documents_after_second[0]["checksum"]
    assert fetch_count["n"] == first_count * 2  # both syncs fetch+checksum, but write nothing new


@pytest.mark.asyncio
async def test_web_connector_incremental_update_and_addition(
    client: TestClient, monkeypatch
) -> None:
    urls = ["https://docs.example.com/a", "https://docs.example.com/b"]
    bodies = {
        "https://docs.example.com/a": b"version 1",
        "https://docs.example.com/b": b"stays same",
    }

    def responder(method, url, kwargs):
        if method == "HEAD":
            return _FakeResponse(status_code=200, headers={})
        return _FakeResponse(status_code=200, content=bodies[url])

    _mock_http(monkeypatch, responder)
    token, org_id = _register_login_and_create_org(client)
    source_id = _create_web_connector(client, token, org_id, urls)
    await _run_sync(org_id, source_id)

    documents_before = client.get(
        f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token)
    ).json()
    checksum_before = {d["title"]: d["checksum"] for d in documents_before}

    bodies["https://docs.example.com/a"] = b"version 2 -- changed"  # "a" changed, "b" untouched
    urls.append("https://docs.example.com/c")  # a new url added to the connector's config
    bodies["https://docs.example.com/c"] = b"brand new"
    # Update the connector's own config to add the third URL -- there's no
    # PATCH-connector-config endpoint in v1, so this reaches through the
    # same public service function the router itself uses.
    async with session_factory() as db:
        source = await documents_service.get_source(db, uuid.UUID(org_id), uuid.UUID(source_id))
        await documents_service.update_source(
            db, uuid.UUID(org_id), uuid.UUID(source_id), config={**source.config, "url_list": urls}
        )

    await _run_sync(org_id, source_id)

    documents_after = client.get(
        f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token)
    ).json()
    checksum_after = {d["title"]: d["checksum"] for d in documents_after}

    assert set(checksum_after) == {
        "https://docs.example.com/a",
        "https://docs.example.com/b",
        "https://docs.example.com/c",
    }
    assert (
        checksum_after["https://docs.example.com/a"]
        != checksum_before["https://docs.example.com/a"]
    )
    assert (
        checksum_after["https://docs.example.com/b"]
        == checksum_before["https://docs.example.com/b"]
    )


# --- deletion detection ---


@pytest.mark.asyncio
async def test_web_connector_sync_soft_deletes_removed_urls(
    client: TestClient, monkeypatch
) -> None:
    urls = ["https://docs.example.com/a", "https://docs.example.com/b"]

    def responder(method, url, kwargs):
        if method == "HEAD":
            return _FakeResponse(status_code=200, headers={})
        return _FakeResponse(status_code=200, content=b"content")

    _mock_http(monkeypatch, responder)
    token, org_id = _register_login_and_create_org(client)
    source_id = _create_web_connector(client, token, org_id, urls)
    await _run_sync(org_id, source_id)
    assert (
        len(client.get(f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token)).json())
        == 2
    )

    async with session_factory() as db:
        source = await documents_service.get_source(db, uuid.UUID(org_id), uuid.UUID(source_id))
        await documents_service.update_source(
            db,
            uuid.UUID(org_id),
            uuid.UUID(source_id),
            config={**source.config, "url_list": urls[:1]},  # "b" removed
        )
    await _run_sync(org_id, source_id)

    remaining = client.get(f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token)).json()
    assert len(remaining) == 1
    assert remaining[0]["title"] == "https://docs.example.com/a"


# --- github connector: cheap no-op + basic sync ---


@pytest.mark.asyncio
async def test_github_sync_skips_tree_listing_when_sha_unchanged(monkeypatch) -> None:
    tree_calls = {"n": 0}

    def responder(method, url, kwargs):
        if "/commits/" in url:
            return _FakeResponse(status_code=200, json_data={"sha": "same-sha"})
        if "/git/trees/" in url:
            tree_calls["n"] += 1
            return _FakeResponse(status_code=200, json_data={"tree": []})
        raise AssertionError(f"unexpected call: {url}")

    _mock_http(monkeypatch, responder)

    from app.modules.connectors.github import GitHubConnector

    connector = GitHubConnector()
    items, new_cursor = await connector.list_changes(
        {"repo": "octocat/hello", "branch": "main", "oauth": {"access_token": "tok"}}, "same-sha"
    )
    assert items == []
    assert new_cursor == "same-sha"
    assert tree_calls["n"] == 0  # the cheap no-op -- tree endpoint never called


@pytest.mark.asyncio
async def test_github_connector_full_sync_creates_documents(
    client: TestClient, monkeypatch
) -> None:
    def responder(method, url, kwargs):
        if "/commits/" in url:
            return _FakeResponse(status_code=200, json_data={"sha": "abc123"})
        if "/git/trees/" in url:
            return _FakeResponse(
                status_code=200,
                json_data={
                    "tree": [
                        {"path": "README.md", "type": "blob", "sha": "blob1"},
                        {"path": "docs/guide.md", "type": "blob", "sha": "blob2"},
                        {"path": "src", "type": "tree", "sha": "treeblob"},
                    ]
                },
            )
        if "/contents/" in url:
            return _FakeResponse(status_code=200, content=f"content for {url}".encode())
        raise AssertionError(f"unexpected call: {url}")

    _mock_http(monkeypatch, responder)

    token, org_id = _register_login_and_create_org(client)
    user_id = client.get(f"{AUTH_PREFIX}/me", headers=_auth_headers(token)).json()["id"]
    async with session_factory() as db:
        source = await documents_service.create_source(
            db,
            uuid.UUID(org_id),
            "github",
            "octocat/hello",
            {
                "repo": "octocat/hello",
                "branch": "main",
                "connected_by_user_id": user_id,
                "cursor": None,
                "oauth": {
                    "access_token": encrypt_token("gho_faketoken"),
                    "refresh_token": None,
                    "expires_at": None,
                },
            },
        )
    await _run_sync(org_id, str(source.id))

    documents = client.get(f"{ORGS_PREFIX}/{org_id}/documents", headers=_auth_headers(token)).json()
    assert len(documents) == 2  # the "tree"-type entry is not a file, correctly excluded
    titles = {d["title"] for d in documents}
    assert titles == {"README.md", "docs/guide.md"}


# --- OAuth callback flow ---


@pytest.mark.asyncio
async def test_github_oauth_callback_creates_connector_with_encrypted_token(
    client: TestClient, monkeypatch
) -> None:
    def responder(method, url, kwargs):
        assert url == "https://github.com/login/oauth/access_token"
        return _FakeResponse(status_code=200, json_data={"access_token": "gho_realtoken123"})

    _mock_http(monkeypatch, responder)

    token, org_id = _register_login_and_create_org(client)

    state_response = client.get(
        f"{ORGS_PREFIX}/{org_id}/connectors/github/authorize",
        params={"repo": "octocat/hello", "branch": "main"},
        headers=_auth_headers(token),
    )
    assert state_response.status_code == 200
    authorize_url = state_response.json()["authorize_url"]
    query = urllib.parse.urlparse(authorize_url).query
    state = urllib.parse.parse_qs(query)["state"][0]

    callback = client.get(
        "/api/v1/oauth/github/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code in (302, 307)

    connectors = client.get(
        f"{ORGS_PREFIX}/{org_id}/connectors", headers=_auth_headers(token)
    ).json()
    github_connectors = [c for c in connectors if c["type"] == "github"]
    assert len(github_connectors) == 1

    async with session_factory() as db:
        source = await documents_service.get_source(
            db, uuid.UUID(org_id), uuid.UUID(github_connectors[0]["id"])
        )
        assert source.config["oauth"]["access_token"] != "gho_realtoken123"  # stored encrypted
        assert decrypt_token(source.config["oauth"]["access_token"]) == "gho_realtoken123"


def test_github_oauth_callback_rejects_tampered_state(client: TestClient) -> None:
    response = client.get(
        "/api/v1/oauth/github/callback",
        params={"code": "x", "state": "not-a-real-token"},
        follow_redirects=False,
    )
    assert response.status_code == 401


# --- RBAC / tenant isolation ---


def test_viewer_cannot_create_connector(client: TestClient) -> None:
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
        f"{ORGS_PREFIX}/{org_id}/connectors",
        json={"name": "W", "url_list": ["https://docs.example.com/x"]},
        headers=_auth_headers(viewer_token),
    )
    assert response.status_code == 403


def test_connector_in_one_org_is_invisible_to_another(client: TestClient) -> None:
    token_a, org_a = _register_login_and_create_org(client)
    _token_b, org_b = _register_login_and_create_org(client)
    source_id = _create_web_connector(client, token_a, org_a, ["https://docs.example.com/x"])

    response = client.get(
        f"{ORGS_PREFIX}/{org_b}/connectors/{source_id}", headers=_auth_headers(token_a)
    )
    assert response.status_code == 404
