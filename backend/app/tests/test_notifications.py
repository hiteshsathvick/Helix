import uuid
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.redis import get_redis_client
from app.core.tenancy import set_tenant_context
from app.main import app
from app.modules.connectors import service as connectors_service
from app.modules.notifications import service as notifications_service
from app.modules.notifications import tasks as notifications_tasks
from app.modules.notifications.models import Notification
from app.modules.notifications.providers import EmailProvider

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


class _FakeEmailProvider(EmailProvider):
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def fake_email_provider(monkeypatch) -> _FakeEmailProvider:
    provider = _FakeEmailProvider()
    monkeypatch.setattr(notifications_service, "get_email_provider", lambda: provider)
    return provider


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


# --- preferences: defaults + honoring ---


def test_get_prefs_returns_defaults_before_any_are_set(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    prefs = client.get(
        f"{ORGS_PREFIX}/{org_id}/notification-prefs", headers=_auth_headers(token)
    ).json()

    # Every (channel, event) combination, defaulted to enabled/immediate,
    # even though the user has never touched a preference row.
    assert {(p["channel"], p["event"]) for p in prefs} == {
        ("email", "notify.manual"),
        ("in_app", "notify.manual"),
        ("email", "connector.sync_failed"),
        ("in_app", "connector.sync_failed"),
    }
    assert all(p["enabled"] and p["frequency"] == "immediate" for p in prefs)


def test_update_prefs_persists_and_is_reflected_in_get(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    updated = client.put(
        f"{ORGS_PREFIX}/{org_id}/notification-prefs",
        json={
            "prefs": [
                {"channel": "email", "event": "notify.manual", "enabled": False},
                {
                    "channel": "email",
                    "event": "connector.sync_failed",
                    "enabled": True,
                    "frequency": "digest",
                },
            ]
        },
        headers=_auth_headers(token),
    ).json()
    by_key = {(p["channel"], p["event"]): p for p in updated}
    assert by_key[("email", "notify.manual")]["enabled"] is False
    assert by_key[("email", "connector.sync_failed")]["frequency"] == "digest"

    refetched = client.get(
        f"{ORGS_PREFIX}/{org_id}/notification-prefs", headers=_auth_headers(token)
    ).json()
    by_key = {(p["channel"], p["event"]): p for p in refetched}
    assert by_key[("email", "notify.manual")]["enabled"] is False
    assert by_key[("email", "connector.sync_failed")]["frequency"] == "digest"


@pytest.mark.asyncio
async def test_notify_skips_channel_the_recipient_disabled(client: TestClient) -> None:
    token, org_id, user_id = _register_login_and_create_org(client)
    client.put(
        f"{ORGS_PREFIX}/{org_id}/notification-prefs",
        json={"prefs": [{"channel": "email", "event": "notify.manual", "enabled": False}]},
        headers=_auth_headers(token),
    )

    async with session_factory() as db:
        created = await notifications_service.notify(
            db,
            uuid.UUID(org_id),
            uuid.UUID(user_id),
            "notify.manual",
            {"subject": "s", "message": "m"},
        )

    channels = {n.channel for n in created}
    assert channels == {"in_app"}  # email suppressed by the disabled pref


@pytest.mark.asyncio
async def test_notify_raises_not_found_for_non_member(client: TestClient) -> None:
    from app.core.errors import NotFoundError

    _token, org_id, _user_id = _register_login_and_create_org(client)
    async with session_factory() as db:
        with pytest.raises(NotFoundError):
            await notifications_service.notify(
                db,
                uuid.UUID(org_id),
                uuid.uuid4(),
                "notify.manual",
                {"subject": "s", "message": "m"},
            )


# --- delivery: immediate email ---


@pytest.mark.asyncio
async def test_immediate_email_notification_is_sent_and_marked(
    client: TestClient, fake_email_provider: _FakeEmailProvider
) -> None:
    token, org_id, user_id = _register_login_and_create_org(client)
    async with session_factory() as db:
        created = await notifications_service.notify(
            db,
            uuid.UUID(org_id),
            uuid.UUID(user_id),
            "notify.manual",
            {"subject": "Hello", "message": "World"},
        )
    email_notification = next(n for n in created if n.channel == "email")
    assert email_notification.status == "pending"

    async with session_factory() as db:
        await notifications_service.send_one(db, uuid.UUID(org_id), email_notification.id)

    assert len(fake_email_provider.sent) == 1
    assert fake_email_provider.sent[0]["subject"] == "Hello"
    assert fake_email_provider.sent[0]["body"] == "World"

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        refreshed = await db.get(Notification, email_notification.id)
        assert refreshed is not None
        assert refreshed.status == "sent"


@pytest.mark.asyncio
async def test_send_notification_task_marks_failed_only_on_last_attempt(
    client: TestClient, monkeypatch
) -> None:
    token, org_id, user_id = _register_login_and_create_org(client)

    class _FailingProvider(EmailProvider):
        async def send(self, *, to: str, subject: str, body: str) -> None:
            raise RuntimeError("smtp down")

    monkeypatch.setattr(notifications_service, "get_email_provider", lambda: _FailingProvider())

    async with session_factory() as db:
        created = await notifications_service.notify(
            db,
            uuid.UUID(org_id),
            uuid.UUID(user_id),
            "notify.manual",
            {"subject": "s", "message": "m"},
        )
    notification_id = next(n for n in created if n.channel == "email").id

    with pytest.raises(RuntimeError):
        await notifications_tasks.send_notification_task(
            {"job_try": 1}, str(notification_id), org_id
        )
    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        mid_attempt = await db.get(Notification, notification_id)
        assert mid_attempt is not None
        assert mid_attempt.status == "pending"  # not yet exhausted -- left for Arq's retry

    with pytest.raises(RuntimeError):
        await notifications_tasks.send_notification_task(
            {"job_try": 3}, str(notification_id), org_id
        )
    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        last_attempt = await db.get(Notification, notification_id)
        assert last_attempt is not None
        assert last_attempt.status == "failed"
        assert last_attempt.error == "smtp down"


# --- delivery: digest batching ---


@pytest.mark.asyncio
async def test_digest_frequency_queues_instead_of_sending_immediately(
    client: TestClient, fake_email_provider: _FakeEmailProvider
) -> None:
    token, org_id, user_id = _register_login_and_create_org(client)
    client.put(
        f"{ORGS_PREFIX}/{org_id}/notification-prefs",
        json={
            "prefs": [
                {
                    "channel": "email",
                    "event": "notify.manual",
                    "enabled": True,
                    "frequency": "digest",
                }
            ]
        },
        headers=_auth_headers(token),
    )

    async with session_factory() as db:
        created = await notifications_service.notify(
            db,
            uuid.UUID(org_id),
            uuid.UUID(user_id),
            "notify.manual",
            {"subject": "s", "message": "m"},
        )
    email_notification = next(n for n in created if n.channel == "email")
    assert email_notification.status == "queued_for_digest"
    assert fake_email_provider.sent == []  # not sent inline


@pytest.mark.asyncio
async def test_digest_sweep_sends_one_combined_email_per_user(
    client: TestClient, fake_email_provider: _FakeEmailProvider
) -> None:
    token, org_id, user_id = _register_login_and_create_org(client)
    client.put(
        f"{ORGS_PREFIX}/{org_id}/notification-prefs",
        json={
            "prefs": [
                {
                    "channel": "email",
                    "event": "notify.manual",
                    "enabled": True,
                    "frequency": "digest",
                }
            ]
        },
        headers=_auth_headers(token),
    )

    async with session_factory() as db:
        await notifications_service.notify(
            db,
            uuid.UUID(org_id),
            uuid.UUID(user_id),
            "notify.manual",
            {"subject": "One", "message": "first"},
        )
        await notifications_service.notify(
            db,
            uuid.UUID(org_id),
            uuid.UUID(user_id),
            "notify.manual",
            {"subject": "Two", "message": "second"},
        )

    await notifications_tasks.send_digest_task({})

    # The sweep is platform-wide (every org, per notifications/tasks.py),
    # so filter to this test's own recipient rather than asserting on the
    # sweep's total -- other tests in the same run may also have queued
    # digest-frequency notifications for their own orgs/recipients.
    me = client.get(f"{AUTH_PREFIX}/me", headers=_auth_headers(token)).json()["email"]
    sent_to_me = [e for e in fake_email_provider.sent if e["to"] == me]
    assert len(sent_to_me) == 1  # one combined email, not two
    assert "first" in sent_to_me[0]["body"]
    assert "second" in sent_to_me[0]["body"]

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        result = await db.execute(
            select(Notification).where(Notification.org_id == uuid.UUID(org_id))
        )
        statuses = {n.status for n in result.scalars().all() if n.channel == "email"}
        assert statuses == {"sent"}


# --- in-app inbox: pagination + read state ---


@pytest.mark.asyncio
async def test_inbox_pagination_mark_read_and_mark_all_read(client: TestClient) -> None:
    token, org_id, user_id = _register_login_and_create_org(client)
    async with session_factory() as db:
        for i in range(3):
            await notifications_service.notify(
                db,
                uuid.UUID(org_id),
                uuid.UUID(user_id),
                "notify.manual",
                {"subject": f"s{i}", "message": f"m{i}"},
            )

    first_page = client.get(
        f"{ORGS_PREFIX}/{org_id}/notifications", params={"limit": 2}, headers=_auth_headers(token)
    ).json()
    assert len(first_page["results"]) == 2
    assert first_page["next_cursor"] is not None

    seen_ids: set[str] = set()
    cursor: str | None = None
    pages = 0
    while True:
        page = client.get(
            f"{ORGS_PREFIX}/{org_id}/notifications",
            params={"limit": 2, **({"cursor": cursor} if cursor else {})},
            headers=_auth_headers(token),
        ).json()
        seen_ids.update(n["id"] for n in page["results"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen_ids) == 6  # 3 notify() calls x 2 channels (email + in_app), no overlap/skip
    assert pages == 3  # 6 results at 2/page

    unread_id = first_page["results"][0]["id"]
    assert first_page["results"][0]["read_at"] is None
    read = client.post(
        f"{ORGS_PREFIX}/{org_id}/notifications/{unread_id}/read", headers=_auth_headers(token)
    ).json()
    assert read["read_at"] is not None

    client.post(f"{ORGS_PREFIX}/{org_id}/notifications/read-all", headers=_auth_headers(token))
    all_after = client.get(
        f"{ORGS_PREFIX}/{org_id}/notifications", params={"limit": 50}, headers=_auth_headers(token)
    ).json()
    assert all(n["read_at"] is not None for n in all_after["results"])


@pytest.mark.asyncio
async def test_marking_another_users_notification_read_is_not_found(client: TestClient) -> None:
    owner_token, org_id, owner_user_id = _register_login_and_create_org(client)

    other_email = _unique_email()
    other_password = "a-strong-password-1"
    client.post(f"{AUTH_PREFIX}/register", json={"email": other_email, "password": other_password})
    other_token = client.post(
        f"{AUTH_PREFIX}/login", json={"email": other_email, "password": other_password}
    ).json()["access_token"]
    invite = client.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": other_email},
        headers=_auth_headers(owner_token),
    ).json()
    client.post(f"/api/v1/invitations/{invite['token']}/accept", headers=_auth_headers(other_token))

    async with session_factory() as db:
        created = await notifications_service.notify(
            db,
            uuid.UUID(org_id),
            uuid.UUID(owner_user_id),
            "notify.manual",
            {"subject": "s", "message": "m"},
        )
        notification_id = str(next(n for n in created if n.channel == "in_app").id)

    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/notifications/{notification_id}/read",
        headers=_auth_headers(other_token),
    )
    assert response.status_code == 404


# --- wiring: connector sync failure ---


class _FakeResponse:
    def __init__(self, status_code: int = 200, content: bytes = b"", headers=None) -> None:
        self.status_code = status_code
        self.content = content
        self.text = content.decode() if isinstance(content, bytes) else content
        self.headers = headers or {}

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

    async def get(self, url, **kwargs) -> Any:
        return self._responder("GET", url, kwargs)

    async def head(self, url, **kwargs) -> Any:
        return self._responder("HEAD", url, kwargs)


@pytest.mark.asyncio
async def test_connector_sync_failure_notifies_the_connecting_user(
    client: TestClient, monkeypatch
) -> None:
    def responder(method, url, kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeClient(responder, **kwargs))
    monkeypatch.setattr(get_settings(), "connector_web_allowlist", ["docs.example.com"])

    token, org_id, _user_id = _register_login_and_create_org(client)
    source_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/connectors",
        json={"name": "Docs", "url_list": ["https://docs.example.com/a"]},
        headers=_auth_headers(token),
    ).json()["id"]

    async with session_factory() as db:
        with pytest.raises(Exception):  # noqa: B017 -- run_sync re-raises after notifying
            await connectors_service.run_sync(db, uuid.UUID(org_id), uuid.UUID(source_id))

    inbox = client.get(f"{ORGS_PREFIX}/{org_id}/notifications", headers=_auth_headers(token)).json()
    failure_notifications = [
        n for n in inbox["results"] if n["event_type"] == "connector.sync_failed"
    ]
    assert len(failure_notifications) == 2  # email + in_app, both enabled by default
    email_notification = next(n for n in failure_notifications if n["channel"] == "email")
    assert "Docs" in email_notification["subject"]


# --- tenant isolation ---


@pytest.mark.asyncio
async def test_notifications_in_one_org_are_invisible_from_another(client: TestClient) -> None:
    token_a, org_a, user_a = _register_login_and_create_org(client)
    token_b, org_b, _user_b = _register_login_and_create_org(client)

    async with session_factory() as db:
        await notifications_service.notify(
            db,
            uuid.UUID(org_a),
            uuid.UUID(user_a),
            "notify.manual",
            {"subject": "s", "message": "m"},
        )

    inbox_b = client.get(
        f"{ORGS_PREFIX}/{org_b}/notifications", headers=_auth_headers(token_b)
    ).json()
    assert inbox_b["results"] == []
