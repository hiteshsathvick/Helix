import hashlib
import hmac
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.redis import get_redis_client
from app.core.tenancy import set_tenant_context
from app.main import app
from app.modules.billing import service as billing_service
from app.modules.billing.models import Subscription
from app.modules.orgs.system_roles import ADMIN_ROLE_ID

AUTH_PREFIX = "/api/v1/auth"
ORGS_PREFIX = "/api/v1/orgs"
WEBHOOK_URL = "/api/v1/webhooks/stripe"


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
def _stripe_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret")
    monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro_test")
    monkeypatch.setattr(settings, "stripe_price_id_enterprise", "price_enterprise_test")


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


def _invite_and_accept_as_admin(client: TestClient, owner_token: str, org_id: str) -> str:
    """Registers a second user, invites+accepts them into org_id, promotes
    them to Admin, and returns their access token."""
    email = _unique_email()
    password = "a-strong-password-1"
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": password})
    token = client.post(f"{AUTH_PREFIX}/login", json={"email": email, "password": password}).json()[
        "access_token"
    ]
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
        json={"role_id": str(ADMIN_ROLE_ID)},
        headers=_auth_headers(owner_token),
    )
    return token


def _sign(payload: bytes, secret: str, *, timestamp: int | None = None) -> str:
    ts = str(timestamp if timestamp is not None else int(time.time()))
    signed_payload = f"{ts}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


# --- RBAC: billing is Owner-only, unlike every other *:manage permission ---


def test_admin_cannot_view_billing_only_owner_can(client: TestClient) -> None:
    owner_token, org_id, _owner_id = _register_login_and_create_org(client)
    admin_token = _invite_and_accept_as_admin(client, owner_token, org_id)

    owner_response = client.get(
        f"{ORGS_PREFIX}/{org_id}/billing", headers=_auth_headers(owner_token)
    )
    assert owner_response.status_code == 200

    admin_response = client.get(
        f"{ORGS_PREFIX}/{org_id}/billing", headers=_auth_headers(admin_token)
    )
    assert admin_response.status_code == 403


def test_billing_endpoints_require_membership(client: TestClient) -> None:
    token_a, org_a, _ = _register_login_and_create_org(client)
    _token_b, org_b, _ = _register_login_and_create_org(client)
    response = client.get(f"{ORGS_PREFIX}/{org_b}/billing", headers=_auth_headers(token_a))
    assert response.status_code == 404


# --- billing summary defaults ---


def test_new_org_defaults_to_free_plan(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    summary = client.get(f"{ORGS_PREFIX}/{org_id}/billing", headers=_auth_headers(token)).json()
    assert summary["plan"] == "free"
    assert summary["status"] == "none"
    assert summary["seats_used"] == 1  # just the owner
    assert summary["seats_limit"] == 3
    assert summary["monthly_cost_cap_usd"] == 5.0


# --- seat quota ---


def test_invitation_blocked_once_free_plan_seat_limit_reached(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    # Free plan seats_limit=3; owner already occupies 1 seat.
    for _ in range(2):
        response = client.post(
            f"{ORGS_PREFIX}/{org_id}/invitations",
            json={"email": _unique_email()},
            headers=_auth_headers(token),
        )
        assert response.status_code == 201

    blocked = client.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": _unique_email()},
        headers=_auth_headers(token),
    )
    assert blocked.status_code == 402
    assert blocked.json()["error"]["code"] == "quota_exceeded"


# --- checkout ---


def test_checkout_creates_customer_and_session(client: TestClient, monkeypatch) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)

    monkeypatch.setattr(
        billing_service.stripe_client, "create_customer", lambda org_id, name: "cus_test123"
    )
    monkeypatch.setattr(
        billing_service.stripe_client,
        "create_checkout_session",
        lambda **kwargs: ("cs_test123", "https://checkout.stripe.com/test-session"),
    )

    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/billing/checkout",
        json={"plan": "pro"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://checkout.stripe.com/test-session"


def test_checkout_rejects_plan_with_no_price_configured(client: TestClient, monkeypatch) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    monkeypatch.setattr(get_settings(), "stripe_price_id_enterprise", "")

    response = client.post(
        f"{ORGS_PREFIX}/{org_id}/billing/checkout",
        json={"plan": "enterprise"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 409


# --- cancel ---


def test_cancel_without_a_subscription_conflicts(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    response = client.post(f"{ORGS_PREFIX}/{org_id}/billing/cancel", headers=_auth_headers(token))
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_cancel_schedules_stripe_cancellation(client: TestClient, monkeypatch) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        db.add(Subscription(org_id=uuid.UUID(org_id), stripe_subscription_id="sub_test123"))
        await db.commit()

    calls = []
    monkeypatch.setattr(
        billing_service.stripe_client,
        "cancel_subscription_at_period_end",
        lambda sub_id: calls.append(sub_id),
    )

    response = client.post(f"{ORGS_PREFIX}/{org_id}/billing/cancel", headers=_auth_headers(token))
    assert response.status_code == 204
    assert calls == ["sub_test123"]


# --- webhook signature verification (real HMAC, no network call) ---


def test_webhook_rejects_tampered_signature(client: TestClient) -> None:
    payload = b'{"type": "checkout.session.completed", "data": {"object": {}}}'
    bad_header = _sign(payload, "wrong_secret")
    response = client.post(WEBHOOK_URL, content=payload, headers={"stripe-signature": bad_header})
    assert response.status_code == 401


def test_webhook_rejects_stale_timestamp(client: TestClient) -> None:
    payload = b'{"type": "checkout.session.completed", "data": {"object": {}}}'
    old_header = _sign(payload, "whsec_test_secret", timestamp=int(time.time()) - 10_000)
    response = client.post(WEBHOOK_URL, content=payload, headers={"stripe-signature": old_header})
    assert response.status_code == 401


def test_webhook_accepts_validly_signed_payload_with_no_org_metadata(client: TestClient) -> None:
    # No org_id in metadata -- service.py logs and ignores rather than
    # erroring, so a *valid* signature with unresolvable content still 204s
    # (Stripe would otherwise retry forever on something we'll never solve).
    payload = b'{"type": "checkout.session.completed", "data": {"object": {"metadata": {}}}}'
    header = _sign(payload, "whsec_test_secret")
    response = client.post(WEBHOOK_URL, content=payload, headers={"stripe-signature": header})
    assert response.status_code == 204


# --- webhook event handling (business logic, event dispatch tested directly) ---


@pytest.mark.asyncio
async def test_checkout_completed_event_activates_plan_and_resets_cap(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"org_id": org_id, "plan": "pro"},
                "customer": "cus_abc",
                "subscription": "sub_abc",
            }
        },
    }
    async with session_factory() as db:
        await billing_service.handle_webhook_event(db, event)

    summary = client.get(f"{ORGS_PREFIX}/{org_id}/billing", headers=_auth_headers(token)).json()
    assert summary["plan"] == "pro"
    assert summary["status"] == "active"
    assert summary["seats_limit"] == 20
    assert summary["monthly_cost_cap_usd"] == 100.0  # reset to the pro plan's included cap


@pytest.mark.asyncio
async def test_subscription_deleted_event_reverts_to_free(client: TestClient) -> None:
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
        await billing_service.handle_webhook_event(
            db,
            {
                "type": "customer.subscription.deleted",
                "data": {"object": {"metadata": {"org_id": org_id}, "customer": "cus_abc"}},
            },
        )

    summary = client.get(f"{ORGS_PREFIX}/{org_id}/billing", headers=_auth_headers(token)).json()
    assert summary["plan"] == "free"
    assert summary["status"] == "canceled"


@pytest.mark.asyncio
async def test_unrecognized_event_type_is_ignored_not_an_error(client: TestClient) -> None:
    _token, org_id, _user_id = _register_login_and_create_org(client)
    async with session_factory() as db:
        # Must not raise -- Stripe sends far more event types than we
        # subscribe to.
        await billing_service.handle_webhook_event(
            db, {"type": "invoice.paid", "data": {"object": {"metadata": {"org_id": org_id}}}}
        )


# --- usage metering ---


@pytest.mark.asyncio
async def test_record_usage_and_monthly_total(client: TestClient) -> None:
    _token, org_id, _user_id = _register_login_and_create_org(client)
    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        await billing_service.record_usage(db, uuid.UUID(org_id), "assistant_query", 100, 0.01)
        await billing_service.record_usage(db, uuid.UUID(org_id), "agent_run", 200, 0.02)
        await db.commit()

    async with session_factory() as db:
        total = await billing_service.get_monthly_usage_usd(db, uuid.UUID(org_id))
    assert total == pytest.approx(0.03)


def test_usage_summary_grouped_by_kind(client: TestClient) -> None:
    token, org_id, _user_id = _register_login_and_create_org(client)
    import asyncio

    async def _seed() -> None:
        async with session_factory() as db:
            await set_tenant_context(db, uuid.UUID(org_id))
            await billing_service.record_usage(db, uuid.UUID(org_id), "assistant_query", 100, 0.01)
            await billing_service.record_usage(db, uuid.UUID(org_id), "assistant_query", 50, 0.005)
            await billing_service.record_usage(db, uuid.UUID(org_id), "agent_run", 200, 0.02)
            await db.commit()

    asyncio.run(_seed())

    usage = client.get(f"{ORGS_PREFIX}/{org_id}/usage", headers=_auth_headers(token)).json()
    by_kind = {item["kind"]: item for item in usage["items"]}
    assert by_kind["assistant_query"]["quantity"] == 150
    assert by_kind["assistant_query"]["cost_usd"] == pytest.approx(0.015)
    assert by_kind["agent_run"]["quantity"] == 200
    assert usage["total_cost_usd"] == pytest.approx(0.035)
    assert usage["monthly_cost_cap_usd"] == 5.0


@pytest.mark.asyncio
async def test_usage_events_are_tenant_isolated(client: TestClient) -> None:
    _token_a, org_a, _ = _register_login_and_create_org(client)
    token_b, org_b, _ = _register_login_and_create_org(client)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_a))
        await billing_service.record_usage(db, uuid.UUID(org_a), "assistant_query", 100, 1.0)
        await db.commit()

    usage_b = client.get(f"{ORGS_PREFIX}/{org_b}/usage", headers=_auth_headers(token_b)).json()
    assert usage_b["items"] == []
    assert usage_b["total_cost_usd"] == 0.0


# --- the headline fix: one shared cap across every AI-spending surface ---


@pytest.mark.asyncio
async def test_cost_cap_is_shared_across_assistant_agents_and_workflows(
    client: TestClient,
) -> None:
    """Before Phase 16, assistant/agents/workflows each summed only their
    own table -- an org capped at $X could spend ~$3X total before any
    single check tripped. Spend recorded under one surface must now block
    every surface.
    """
    token, org_id, _user_id = _register_login_and_create_org(client)
    client.put(
        f"{ORGS_PREFIX}/{org_id}/ai-config",
        json={"monthly_cost_cap_usd": 0.001},
        headers=_auth_headers(token),
    )

    # Simulate spend that happened entirely through the agents surface.
    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_id))
        await billing_service.record_usage(db, uuid.UUID(org_id), "agent_run", 1000, 0.002)
        await db.commit()

    from app.core.errors import QuotaExceededError
    from app.modules.assistant import service as assistant_service

    with pytest.raises(QuotaExceededError):
        async with session_factory() as db:
            await assistant_service.assert_within_cost_cap(db, uuid.UUID(org_id))
