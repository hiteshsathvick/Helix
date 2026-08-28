import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import session_factory
from app.core.redis import get_redis_client
from app.core.tenancy import set_tenant_context
from app.main import app
from app.modules.audit import service as audit_service
from app.modules.billing import service as billing_service
from app.modules.orgs.system_roles import ADMIN_ROLE_ID, MEMBER_ROLE_ID

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


def _register(client: TestClient) -> tuple[str, str]:
    email = _unique_email()
    password = "a-strong-password-1"
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": password})
    return email, password


def _login(client: TestClient, email: str, password: str) -> str:
    return client.post(f"{AUTH_PREFIX}/login", json={"email": email, "password": password}).json()[
        "access_token"
    ]


def _register_login_and_create_org(client: TestClient) -> tuple[str, str, str]:
    email, password = _register(client)
    token = _login(client, email, password)
    user_id = client.get(f"{AUTH_PREFIX}/me", headers=_auth_headers(token)).json()["id"]
    org_id = client.post(
        ORGS_PREFIX,
        json={"name": "Org", "slug": f"org-{uuid.uuid4().hex[:8]}"},
        headers=_auth_headers(token),
    ).json()["id"]
    return token, org_id, user_id


def _invite_accept_and_set_role(
    client: TestClient, owner_token: str, org_id: str, role_id: uuid.UUID
) -> tuple[str, str]:
    """Returns (token, user_id) of a new member set to the given role."""
    email, password = _register(client)
    token = _login(client, email, password)
    invite = client.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": email},
        headers=_auth_headers(owner_token),
    ).json()
    client.post(f"/api/v1/invitations/{invite['token']}/accept", headers=_auth_headers(token))
    members = client.get(
        f"{ORGS_PREFIX}/{org_id}/members", headers=_auth_headers(owner_token)
    ).json()
    membership_id = next(m["id"] for m in members if m["email"] == email)
    client.put(
        f"{ORGS_PREFIX}/{org_id}/memberships/{membership_id}/role",
        json={"role_id": str(role_id)},
        headers=_auth_headers(owner_token),
    )
    user_id = client.get(f"{AUTH_PREFIX}/me", headers=_auth_headers(token)).json()["id"]
    return token, user_id


def _last_action(client: TestClient, token: str, org_id: str, action: str) -> dict:
    logs = client.get(
        f"{ORGS_PREFIX}/{org_id}/audit", params={"action": action}, headers=_auth_headers(token)
    ).json()["results"]
    assert logs, f"no audit row found for action {action!r}"
    return logs[0]


# --- auth events ---


def test_login_is_audited_once_an_org_exists(client: TestClient) -> None:
    email, password = _register(client)
    token = _login(client, email, password)
    org_id = client.post(
        ORGS_PREFIX,
        json={"name": "Org", "slug": f"org-{uuid.uuid4().hex[:8]}"},
        headers=_auth_headers(token),
    ).json()["id"]

    # A second login, now that the user has an active org, is what gets
    # scoped and audited -- the first login (before org creation) had
    # nothing to scope it to.
    _login(client, email, password)

    row = _last_action(client, token, org_id, "auth.login")
    assert row["actor_email"] == email


def test_logout_is_audited(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    client.post(f"{AUTH_PREFIX}/logout", headers=_auth_headers(token))

    # logout revoked the cookie, but a fresh login still works for querying.
    row = _last_action(client, token, org_id, "auth.logout")
    assert row["action"] == "auth.logout"


# --- membership / permission events ---


def test_invitation_created_and_accepted_are_audited(client: TestClient) -> None:
    owner_token, org_id, owner_id = _register_login_and_create_org(client)
    email, password = _register(client)
    invite = client.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": email},
        headers=_auth_headers(owner_token),
    ).json()

    created = _last_action(client, owner_token, org_id, "invitation.created")
    assert created["actor_id"] == owner_id
    assert created["metadata"]["email"] == email

    invitee_token = _login(client, email, password)
    client.post(
        f"/api/v1/invitations/{invite['token']}/accept", headers=_auth_headers(invitee_token)
    )

    accepted = _last_action(client, owner_token, org_id, "invitation.accepted")
    assert accepted["actor_email"] == email


def test_member_role_updated_is_audited(client: TestClient) -> None:
    owner_token, org_id, owner_id = _register_login_and_create_org(client)
    _member_token, member_id = _invite_accept_and_set_role(
        client, owner_token, org_id, MEMBER_ROLE_ID
    )

    row = _last_action(client, owner_token, org_id, "member.role_updated")
    assert row["actor_id"] == owner_id
    assert row["resource_type"] == "membership"


def test_permission_denied_is_audited(client: TestClient) -> None:
    owner_token, org_id, _owner_id = _register_login_and_create_org(client)
    member_token, member_id = _invite_accept_and_set_role(
        client, owner_token, org_id, MEMBER_ROLE_ID
    )

    # Members don't have billing:manage.
    denied = client.get(f"{ORGS_PREFIX}/{org_id}/billing", headers=_auth_headers(member_token))
    assert denied.status_code == 403

    row = _last_action(client, owner_token, org_id, "permission.denied")
    assert row["actor_id"] == member_id
    assert row["metadata"]["permission"] == "billing:manage"


# --- config / billing events ---


def test_ai_config_updated_is_audited(client: TestClient) -> None:
    token, org_id, user_id = _register_login_and_create_org(client)
    client.put(
        f"{ORGS_PREFIX}/{org_id}/ai-config",
        json={"monthly_cost_cap_usd": 12.5},
        headers=_auth_headers(token),
    )

    row = _last_action(client, token, org_id, "ai_config.updated")
    assert row["actor_id"] == user_id
    assert row["metadata"]["ai_monthly_cost_cap_usd"] == 12.5


@pytest.mark.asyncio
async def test_billing_checkout_and_cancel_are_audited(client: TestClient, monkeypatch) -> None:
    token, org_id, user_id = _register_login_and_create_org(client)
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "stripe_price_id_pro", "price_pro_test")
    monkeypatch.setattr(
        billing_service.stripe_client, "create_customer", lambda org_id, name: "cus_test123"
    )
    monkeypatch.setattr(
        billing_service.stripe_client,
        "create_checkout_session",
        lambda **kwargs: ("cs_test123", "https://checkout.stripe.com/test"),
    )
    client.post(
        f"{ORGS_PREFIX}/{org_id}/billing/checkout",
        json={"plan": "pro"},
        headers=_auth_headers(token),
    )
    started = _last_action(client, token, org_id, "billing.checkout_started")
    assert started["actor_id"] == user_id

    # start_checkout only ever persists stripe_customer_id -- a real
    # stripe_subscription_id lands via the webhook (checkout.session.
    # completed), not the checkout call itself. Simulate that arriving.
    async with session_factory() as db:
        await billing_service.handle_webhook_event(
            db,
            {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "metadata": {"org_id": org_id, "plan": "pro"},
                        "customer": "cus_test123",
                        "subscription": "sub_test123",
                    }
                },
            },
        )

    monkeypatch.setattr(
        billing_service.stripe_client, "cancel_subscription_at_period_end", lambda sub_id: None
    )
    cancel_response = client.post(
        f"{ORGS_PREFIX}/{org_id}/billing/cancel", headers=_auth_headers(token)
    )
    assert cancel_response.status_code == 204
    cancelled = _last_action(client, token, org_id, "billing.subscription_cancelled")
    assert cancelled["actor_id"] == user_id


@pytest.mark.asyncio
async def test_webhook_plan_change_is_audited_with_no_actor(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    async with session_factory() as db:
        await billing_service.handle_webhook_event(
            db,
            {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "metadata": {"org_id": org_id, "plan": "pro"},
                        "customer": "cus_abc",
                        "subscription": "sub_abc",
                    }
                },
            },
        )

    row = _last_action(client, token, org_id, "billing.plan_changed")
    assert row["actor_id"] is None
    assert row["actor_email"] is None


# --- pagination / filtering ---


def test_audit_log_pagination(client: TestClient) -> None:
    owner_token, org_id, _owner_id = _register_login_and_create_org(client)
    # Free plan's seat limit is 3 (owner + 2) -- exactly 2 invitations can
    # succeed here, per Phase 16's quota.
    for _ in range(2):
        response = client.post(
            f"{ORGS_PREFIX}/{org_id}/invitations",
            json={"email": _unique_email()},
            headers=_auth_headers(owner_token),
        )
        assert response.status_code == 201

    first_page = client.get(
        f"{ORGS_PREFIX}/{org_id}/audit",
        params={"limit": 1, "action": "invitation.created"},
        headers=_auth_headers(owner_token),
    ).json()
    assert len(first_page["results"]) == 1
    assert first_page["next_cursor"] is not None

    second_page = client.get(
        f"{ORGS_PREFIX}/{org_id}/audit",
        params={"limit": 1, "action": "invitation.created", "cursor": first_page["next_cursor"]},
        headers=_auth_headers(owner_token),
    ).json()
    assert len(second_page["results"]) == 1
    assert second_page["next_cursor"] is None

    seen_ids = {r["id"] for r in first_page["results"]} | {r["id"] for r in second_page["results"]}
    assert len(seen_ids) == 2


# --- RBAC / tenant isolation ---


def test_audit_read_requires_permission_member_denied_admin_allowed(client: TestClient) -> None:
    owner_token, org_id, _owner_id = _register_login_and_create_org(client)
    member_token, _member_id = _invite_accept_and_set_role(
        client, owner_token, org_id, MEMBER_ROLE_ID
    )
    admin_token, _admin_id = _invite_accept_and_set_role(client, owner_token, org_id, ADMIN_ROLE_ID)

    member_response = client.get(
        f"{ORGS_PREFIX}/{org_id}/audit", headers=_auth_headers(member_token)
    )
    assert member_response.status_code == 403

    admin_response = client.get(f"{ORGS_PREFIX}/{org_id}/audit", headers=_auth_headers(admin_token))
    assert admin_response.status_code == 200


@pytest.mark.asyncio
async def test_audit_logs_are_tenant_isolated(client: TestClient) -> None:
    token_a, org_a, user_a = _register_login_and_create_org(client)
    token_b, org_b, _user_b = _register_login_and_create_org(client)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_a))
        await audit_service.record(db, uuid.UUID(org_a), uuid.UUID(user_a), "test.event")
        await db.commit()

    logs_b = client.get(f"{ORGS_PREFIX}/{org_b}/audit", headers=_auth_headers(token_b)).json()
    assert logs_b["results"] == []
