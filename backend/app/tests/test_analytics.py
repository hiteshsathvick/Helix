import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import session_factory
from app.core.redis import get_redis_client
from app.core.tenancy import set_tenant_context
from app.main import app
from app.modules.agents.models import AgentRun
from app.modules.audit import service as audit_service
from app.modules.billing import service as billing_service
from app.modules.documents import service as documents_service
from app.modules.orgs.system_roles import ADMIN_ROLE_ID, MEMBER_ROLE_ID
from app.modules.workflows import service as workflows_service
from app.modules.workflows.models import WorkflowRun

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


def _register_login_and_create_org(client: TestClient) -> tuple[str, str, str]:
    email, password = _register(client)
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


def _invite_accept_and_set_role(
    client: TestClient, owner_token: str, org_id: str, role_id: uuid.UUID
) -> str:
    email, password = _register(client)
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
        json={"role_id": str(role_id)},
        headers=_auth_headers(owner_token),
    )
    return token


@pytest.mark.asyncio
async def test_analytics_overview_reflects_usage_runs_and_documents(client: TestClient) -> None:
    token, org_id, user_id = _register_login_and_create_org(client)
    org_uuid, user_uuid = uuid.UUID(org_id), uuid.UUID(user_id)

    agent_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/agents",
        json={"name": "A", "instructions": "help", "allowed_tools": []},
        headers=_auth_headers(token),
    ).json()["id"]

    workflow_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/workflows",
        json={
            "name": "W",
            "graph": {"nodes": [{"id": "start", "type": "trigger", "config": {}}], "edges": []},
        },
        headers=_auth_headers(token),
    ).json()["id"]

    document_id = client.post(
        f"{ORGS_PREFIX}/{org_id}/documents",
        files={"file": ("doc.txt", b"hello world", "text/plain")},
        headers=_auth_headers(token),
    ).json()["id"]

    async with session_factory() as db:
        await set_tenant_context(db, org_uuid)
        version = await workflows_service.get_current_version(db, org_uuid, uuid.UUID(workflow_id))

        db.add_all(
            [
                AgentRun(
                    org_id=org_uuid,
                    agent_id=uuid.UUID(agent_id),
                    triggered_by_user_id=user_uuid,
                    status="completed",
                    input="hi",
                ),
                AgentRun(
                    org_id=org_uuid,
                    agent_id=uuid.UUID(agent_id),
                    triggered_by_user_id=user_uuid,
                    status="completed",
                    input="hi",
                ),
                AgentRun(
                    org_id=org_uuid,
                    agent_id=uuid.UUID(agent_id),
                    triggered_by_user_id=user_uuid,
                    status="failed",
                    input="hi",
                ),
                WorkflowRun(
                    org_id=org_uuid,
                    workflow_id=uuid.UUID(workflow_id),
                    version_id=version.id,
                    status="completed",
                    trigger={},
                    context={},
                ),
            ]
        )
        await db.commit()

        await documents_service.mark_document_status(
            db, org_uuid, uuid.UUID(document_id), "indexed"
        )
        # mark_document_status just committed, which ends the SET LOCAL
        # tenant context RLS needs -- re-set it before the next write.
        await set_tenant_context(db, org_uuid)
        await billing_service.record_usage(db, org_uuid, "assistant_query", 100, 0.05)
        # Directly seeding AgentRun/WorkflowRun rows above bypassed the
        # audited create_run() service functions entirely, so nothing
        # audited has actually happened in this org yet -- seed one
        # audited action directly to give "active users" something real
        # to count.
        await audit_service.record(db, org_uuid, user_uuid, "test.seed")
        await db.commit()

    overview = client.get(
        f"{ORGS_PREFIX}/{org_id}/analytics/overview", headers=_auth_headers(token)
    ).json()

    assert overview["agent_runs_by_status"] == {"completed": 2, "failed": 1}
    assert overview["workflow_runs_by_status"] == {"completed": 1}
    assert overview["documents_by_status"] == {"indexed": 1}
    assert overview["usage"]["total_cost_usd"] == pytest.approx(0.05)
    assert overview["active_users"] == 1


def test_analytics_requires_permission_member_denied_admin_allowed(client: TestClient) -> None:
    owner_token, org_id, _owner_id = _register_login_and_create_org(client)
    member_token = _invite_accept_and_set_role(client, owner_token, org_id, MEMBER_ROLE_ID)
    admin_token = _invite_accept_and_set_role(client, owner_token, org_id, ADMIN_ROLE_ID)

    member_response = client.get(
        f"{ORGS_PREFIX}/{org_id}/analytics/overview", headers=_auth_headers(member_token)
    )
    assert member_response.status_code == 403

    admin_response = client.get(
        f"{ORGS_PREFIX}/{org_id}/analytics/overview", headers=_auth_headers(admin_token)
    )
    assert admin_response.status_code == 200


@pytest.mark.asyncio
async def test_analytics_are_tenant_isolated(client: TestClient) -> None:
    token_a, org_a, _user_a = _register_login_and_create_org(client)
    token_b, org_b, _user_b = _register_login_and_create_org(client)

    async with session_factory() as db:
        await set_tenant_context(db, uuid.UUID(org_a))
        await billing_service.record_usage(db, uuid.UUID(org_a), "assistant_query", 1000, 10.0)
        await db.commit()

    overview_b = client.get(
        f"{ORGS_PREFIX}/{org_b}/analytics/overview", headers=_auth_headers(token_b)
    ).json()
    assert overview_b["usage"]["total_cost_usd"] == 0.0
    assert overview_b["agent_runs_by_status"] == {}
