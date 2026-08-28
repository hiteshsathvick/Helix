import hashlib
import hmac
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.events import publish_event
from app.core.redis import get_redis_client
from app.core.tenancy import set_tenant_context
from app.main import app
from app.modules.api import service as api_service
from app.modules.api.models import WebhookDelivery

AUTH_PREFIX = "/api/v1/auth"
ORGS_PREFIX = "/api/v1/orgs"
PUBLIC_PREFIX = "/api/v1/public"


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


def _register_login_and_create_org(client: TestClient) -> tuple[str, str, str]:
    email = _unique_email()
    password = "a-strong-password-1"
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": password})
    token = client.post(f"{AUTH_PREFIX}/login", json={"email": email, "password": password}).json()[
        "access_token"
    ]
    user_id = client.get(f"{AUTH_PREFIX}/me", headers=_auth_headers(token)).json()["id"]
    org_id = client.post(
        ORGS_PREFIX,
        json={"name": "Org", "slug": f"org-{uuid.uuid4().hex[:8]}"},
        headers=_auth_headers(token),
    ).json()["id"]
    return token, org_id, user_id


def _create_api_key(client: TestClient, token: str, org_id: str, scopes: list[str]) -> str:
    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/api-keys",
        json={"name": "Test key", "scopes": scopes},
        headers=_auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()["raw_key"]


# --- API key management ---


def test_create_list_and_revoke_api_key(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)

    created = client.post(
        f"{ORGS_PREFIX}/{org_id}/api-keys",
        json={"name": "CI key", "scopes": ["search:read"]},
        headers=_auth_headers(token),
    ).json()
    assert created["raw_key"].startswith("hx_")
    assert created["key"]["prefix"] == created["raw_key"][:12]

    listed = client.get(f"{ORGS_PREFIX}/{org_id}/api-keys", headers=_auth_headers(token)).json()
    assert len(listed) == 1
    assert "raw_key" not in listed[0]
    assert "hash" not in listed[0]

    revoke = client.delete(
        f"{ORGS_PREFIX}/{org_id}/api-keys/{created['key']['id']}", headers=_auth_headers(token)
    )
    assert revoke.status_code == 204
    listed_after = client.get(
        f"{ORGS_PREFIX}/{org_id}/api-keys", headers=_auth_headers(token)
    ).json()
    assert listed_after == []

    # The revoked key no longer authenticates.
    denied = client.get(
        f"{PUBLIC_PREFIX}/search",
        params={"q": "x"},
        headers=_auth_headers(created["raw_key"]),
    )
    assert denied.status_code == 401


def test_api_key_management_requires_permission(client: TestClient) -> None:
    owner_token, org_id, _owner_id = _register_login_and_create_org(client)
    email, password = _unique_email(), "a-strong-password-1"
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": password})
    member_token = client.post(
        f"{AUTH_PREFIX}/login", json={"email": email, "password": password}
    ).json()["access_token"]
    invite = client.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": email},
        headers=_auth_headers(owner_token),
    ).json()
    client.post(
        f"/api/v1/invitations/{invite['token']}/accept", headers=_auth_headers(member_token)
    )
    # Default role on accept is Member (system_roles.MEMBER_ROLE_ID) -- no
    # api_keys:manage there.

    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/api-keys",
        json={"name": "nope", "scopes": ["search:read"]},
        headers=_auth_headers(member_token),
    )
    assert response.status_code == 403


# --- public API: scoping ---


def test_public_search_requires_correct_scope(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    docs_only_key = _create_api_key(client, token, org_id, ["documents:read"])

    response = client.get(
        f"{PUBLIC_PREFIX}/search", params={"q": "hello"}, headers=_auth_headers(docs_only_key)
    )
    assert response.status_code == 403


def test_public_search_and_documents_with_correct_scope(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    key = _create_api_key(
        client, token, org_id, ["search:read", "documents:read", "documents:write"]
    )

    upload = client.post(
        f"{PUBLIC_PREFIX}/documents",
        files={"file": ("doc.txt", b"the quick brown fox", "text/plain")},
        headers=_auth_headers(key),
    )
    assert upload.status_code == 201
    assert upload.json()["title"] == "doc.txt"

    listed = client.get(f"{PUBLIC_PREFIX}/documents", headers=_auth_headers(key)).json()
    assert len(listed) == 1

    search = client.get(f"{PUBLIC_PREFIX}/search", params={"q": "fox"}, headers=_auth_headers(key))
    assert search.status_code == 200
    assert "results" in search.json()


def test_public_api_missing_key_is_unauthorized(client: TestClient) -> None:
    response = client.get(f"{PUBLIC_PREFIX}/search", params={"q": "x"})
    assert response.status_code == 401


def test_public_api_tenant_isolation(client: TestClient) -> None:
    token_a, org_a, _ = _register_login_and_create_org(client)
    token_b, org_b, _ = _register_login_and_create_org(client)
    key_a = _create_api_key(client, token_a, org_a, ["documents:read", "documents:write"])
    key_b = _create_api_key(client, token_b, org_b, ["documents:read"])

    client.post(
        f"{PUBLIC_PREFIX}/documents",
        files={"file": ("secret.txt", b"org a only", "text/plain")},
        headers=_auth_headers(key_a),
    )

    listed_via_b = client.get(f"{PUBLIC_PREFIX}/documents", headers=_auth_headers(key_b)).json()
    assert listed_via_b == []


# --- public API: rate limiting ---


def test_public_api_rate_limit(client: TestClient, monkeypatch) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    key = _create_api_key(client, token, org_id, ["documents:read"])
    monkeypatch.setattr(get_settings(), "public_api_rate_limit_max_requests", 2)

    for _ in range(2):
        response = client.get(f"{PUBLIC_PREFIX}/documents", headers=_auth_headers(key))
        assert response.status_code == 200

    limited = client.get(f"{PUBLIC_PREFIX}/documents", headers=_auth_headers(key))
    assert limited.status_code == 429


# --- webhooks: management ---


def test_create_and_list_webhooks_secret_shown_once(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)

    created = client.post(
        f"{ORGS_PREFIX}/{org_id}/webhooks",
        json={"url": "https://example.com/hook", "events": ["document.ingested"]},
        headers=_auth_headers(token),
    ).json()
    assert len(created["secret"]) > 10

    listed = client.get(f"{ORGS_PREFIX}/{org_id}/webhooks", headers=_auth_headers(token)).json()
    assert len(listed) == 1
    assert "secret" not in listed[0]


def test_deactivate_webhook_stops_future_matches(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    created = client.post(
        f"{ORGS_PREFIX}/{org_id}/webhooks",
        json={"url": "https://example.com/hook", "events": ["document.ingested"]},
        headers=_auth_headers(token),
    ).json()

    deactivate = client.delete(
        f"{ORGS_PREFIX}/{org_id}/webhooks/{created['webhook']['id']}", headers=_auth_headers(token)
    )
    assert deactivate.status_code == 204

    listed = client.get(f"{ORGS_PREFIX}/{org_id}/webhooks", headers=_auth_headers(token)).json()
    assert listed[0]["active"] is False


# --- webhook delivery: real HMAC signing, no network calls ---


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)  # type: ignore[arg-type]


class _FakeClient:
    captured: list[dict] = []

    def __init__(self, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, content, headers, **kwargs) -> _FakeResponse:
        _FakeClient.captured.append({"url": url, "content": content, "headers": headers})
        return _FakeResponse(200)


class _FailingClient(_FakeClient):
    async def post(self, url, *, content, headers, **kwargs) -> _FakeResponse:
        _FakeClient.captured.append({"url": url, "content": content, "headers": headers})
        return _FakeResponse(500)


@pytest.mark.asyncio
async def test_webhook_delivery_is_correctly_signed(client: TestClient, monkeypatch) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    webhook = client.post(
        f"{ORGS_PREFIX}/{org_id}/webhooks",
        json={"url": "https://example.com/hook", "events": ["test.custom_event"]},
        headers=_auth_headers(token),
    ).json()

    _FakeClient.captured = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        event = await publish_event(db, uuid.UUID(org_id), "test.custom_event", {"foo": "bar"})
        await api_service.dispatch_webhooks_for_event(db, uuid.UUID(org_id), event.id)
        # dispatch_webhooks_for_event just committed, which ends the SET
        # LOCAL tenant context RLS needs -- re-set it before the raw query
        # below.
        await set_tenant_context(db, uuid.UUID(org_id))

        result = await db.execute(
            WebhookDelivery.__table__.select().where(WebhookDelivery.org_id == uuid.UUID(org_id))
        )
        delivery_row = result.first()
        assert delivery_row is not None

        await api_service.attempt_delivery(db, uuid.UUID(org_id), delivery_row.id)

    assert len(_FakeClient.captured) == 1
    sent = _FakeClient.captured[0]
    assert sent["url"] == "https://example.com/hook"

    body = sent["content"]
    payload = json.loads(body)
    assert payload["type"] == "test.custom_event"
    assert payload["data"] == {"foo": "bar"}

    expected_signature = hmac.new(webhook["secret"].encode(), body, hashlib.sha256).hexdigest()
    assert sent["headers"]["X-Helix-Signature"] == f"sha256={expected_signature}"


@pytest.mark.asyncio
async def test_webhook_delivery_retries_then_marks_failed_on_last_attempt(
    client: TestClient, monkeypatch
) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    client.post(
        f"{ORGS_PREFIX}/{org_id}/webhooks",
        json={"url": "https://example.com/hook", "events": ["test.custom_event"]},
        headers=_auth_headers(token),
    )

    _FakeClient.captured = []
    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)
    monkeypatch.setattr(get_settings(), "webhook_delivery_max_job_attempts", 2)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        event = await publish_event(db, uuid.UUID(org_id), "test.custom_event", {})
        await api_service.dispatch_webhooks_for_event(db, uuid.UUID(org_id), event.id)
        # dispatch_webhooks_for_event just committed, which ends the SET
        # LOCAL tenant context RLS needs -- re-set it before the raw query
        # below.
        await set_tenant_context(db, uuid.UUID(org_id))
        result = await db.execute(
            WebhookDelivery.__table__.select().where(WebhookDelivery.org_id == uuid.UUID(org_id))
        )
        delivery_row = result.first()
        assert delivery_row is not None
        delivery_id = delivery_row.id

    from app.modules.api.tasks import deliver_webhook_task

    with pytest.raises(Exception):  # noqa: B017 -- httpx.HTTPStatusError from the 500
        await deliver_webhook_task({"job_try": 1}, str(delivery_id), org_id)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        mid = await db.get(WebhookDelivery, delivery_id)
        assert mid is not None
        assert mid.status == "pending"  # not yet exhausted

    with pytest.raises(Exception):  # noqa: B017
        await deliver_webhook_task({"job_try": 2}, str(delivery_id), org_id)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        last = await db.get(WebhookDelivery, delivery_id)
        assert last is not None
        assert last.status == "failed"
        assert last.attempts == 2


@pytest.mark.asyncio
async def test_webhook_deliveries_are_listed_for_the_dashboard(
    client: TestClient, monkeypatch
) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    webhook = client.post(
        f"{ORGS_PREFIX}/{org_id}/webhooks",
        json={"url": "https://example.com/hook", "events": ["test.custom_event"]},
        headers=_auth_headers(token),
    ).json()

    _FakeClient.captured = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        event = await publish_event(db, uuid.UUID(org_id), "test.custom_event", {})
        await api_service.dispatch_webhooks_for_event(db, uuid.UUID(org_id), event.id)
        # dispatch_webhooks_for_event just committed, which ends the SET
        # LOCAL tenant context RLS needs -- re-set it before the raw query
        # below.
        await set_tenant_context(db, uuid.UUID(org_id))
        result = await db.execute(
            WebhookDelivery.__table__.select().where(WebhookDelivery.org_id == uuid.UUID(org_id))
        )
        delivery_row = result.first()
        assert delivery_row is not None
        delivery_id = delivery_row.id
        await api_service.attempt_delivery(db, uuid.UUID(org_id), delivery_id)

    deliveries = client.get(
        f"{ORGS_PREFIX}/{org_id}/webhooks/{webhook['webhook']['id']}/deliveries",
        headers=_auth_headers(token),
    ).json()
    assert len(deliveries) == 1
    assert deliveries[0]["status"] == "delivered"
    assert deliveries[0]["event_type"] == "test.custom_event"


# --- audit continuity (Phase 17) ---


def test_api_key_and_webhook_mutations_are_audited(client: TestClient) -> None:
    token, org_id, user_id = _register_login_and_create_org(client)
    client.post(
        f"{ORGS_PREFIX}/{org_id}/api-keys",
        json={"name": "k", "scopes": ["search:read"]},
        headers=_auth_headers(token),
    )
    client.post(
        f"{ORGS_PREFIX}/{org_id}/webhooks",
        json={"url": "https://example.com/hook", "events": ["document.ingested"]},
        headers=_auth_headers(token),
    )

    logs = client.get(f"{ORGS_PREFIX}/{org_id}/audit", headers=_auth_headers(token)).json()[
        "results"
    ]
    actions = {log["action"] for log in logs}
    assert "api_key.created" in actions
    assert "webhook.created" in actions
