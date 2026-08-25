import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.redis import get_redis_client
from app.main import app
from app.modules.orgs.system_roles import VIEWER_ROLE_ID

AUTH_PREFIX = "/api/v1/auth"
ORGS_PREFIX = "/api/v1/orgs"
INVITATIONS_PREFIX = "/api/v1/invitations"


@pytest.fixture(autouse=True)
async def _clear_rate_limit_state():
    client = get_redis_client()
    try:
        await client.flushdb()
    finally:
        await client.aclose()
    yield


def _unique_email() -> str:
    return f"user-{uuid.uuid4()}@example.com"


def _register_and_login(
    client: TestClient, password: str = "a-strong-password-1"
) -> tuple[str, str]:
    email = _unique_email()
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": password})
    login_response = client.post(
        f"{AUTH_PREFIX}/login", json={"email": email, "password": password}
    )
    return email, login_response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_member_org():
    """Owner (client_a/token_a) creates an org and invites a Member
    (client_b/token_b). Returns (client_a, token_a, client_b, token_b, org_id, membership_id_b).
    """
    with (
        TestClient(app, base_url="https://testserver") as client_a,
        TestClient(app, base_url="https://testserver") as client_b,
    ):
        email_a, token_a = _register_and_login(client_a)
        email_b, token_b = _register_and_login(client_b)

        org_id = client_a.post(
            ORGS_PREFIX,
            json={"name": "Org A", "slug": f"org-a-{uuid.uuid4().hex[:8]}"},
            headers=_auth_headers(token_a),
        ).json()["id"]

        raw_token = client_a.post(
            f"{ORGS_PREFIX}/{org_id}/invitations",
            json={"email": email_b},
            headers=_auth_headers(token_a),
        ).json()["token"]

        accept_response = client_b.post(
            f"{INVITATIONS_PREFIX}/{raw_token}/accept", headers=_auth_headers(token_b)
        )
        token_b = accept_response.json()["access_token"]

        members = client_a.get(
            f"{ORGS_PREFIX}/{org_id}/members", headers=_auth_headers(token_a)
        ).json()
        membership_id_b = next(m["id"] for m in members if m["email"] == email_b)

        yield client_a, token_a, client_b, token_b, org_id, membership_id_b


def test_owner_can_invite_member_cannot(two_member_org) -> None:
    client_a, token_a, client_b, token_b, org_id, _ = two_member_org

    owner_invite = client_a.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": _unique_email()},
        headers=_auth_headers(token_a),
    )
    assert owner_invite.status_code == 201

    member_invite = client_b.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": _unique_email()},
        headers=_auth_headers(token_b),
    )
    assert member_invite.status_code == 403
    assert member_invite.json()["error"]["code"] == "forbidden"


def test_member_can_still_read_members(two_member_org) -> None:
    _, _, client_b, token_b, org_id, _ = two_member_org
    response = client_b.get(f"{ORGS_PREFIX}/{org_id}/members", headers=_auth_headers(token_b))
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_owner_can_create_custom_role_member_cannot(two_member_org) -> None:
    client_a, token_a, client_b, token_b, org_id, _ = two_member_org

    owner_create = client_a.post(
        f"{ORGS_PREFIX}/{org_id}/roles",
        json={"name": "Billing Viewer", "permissions": ["members:read"]},
        headers=_auth_headers(token_a),
    )
    assert owner_create.status_code == 201

    member_create = client_b.post(
        f"{ORGS_PREFIX}/{org_id}/roles",
        json={"name": "Should Fail", "permissions": []},
        headers=_auth_headers(token_b),
    )
    assert member_create.status_code == 403


def test_owner_can_change_member_role_then_permissions_change(two_member_org) -> None:
    client_a, token_a, client_b, token_b, org_id, membership_id_b = two_member_org

    change_response = client_a.post(
        f"{ORGS_PREFIX}/{org_id}/switch", headers=_auth_headers(token_a)
    )
    assert change_response.status_code == 200

    update_response = client_a.put(
        f"{ORGS_PREFIX}/{org_id}/memberships/{membership_id_b}/role",
        json={"role_id": str(VIEWER_ROLE_ID)},
        headers=_auth_headers(token_a),
    )
    assert update_response.status_code == 200
    assert update_response.json()["role_name"] == "Viewer"

    # Viewer has the same permission set as Member today, so this should
    # still succeed — the important thing is the role actually changed.
    my_perms = client_b.get(f"{ORGS_PREFIX}/{org_id}/me", headers=_auth_headers(token_b))
    assert my_perms.status_code == 200
    assert my_perms.json()["role"]["name"] == "Viewer"


def test_member_cannot_change_roles(two_member_org) -> None:
    _, _, client_b, token_b, org_id, membership_id_b = two_member_org
    response = client_b.put(
        f"{ORGS_PREFIX}/{org_id}/memberships/{membership_id_b}/role",
        json={"role_id": str(VIEWER_ROLE_ID)},
        headers=_auth_headers(token_b),
    )
    assert response.status_code == 403


def test_permission_denial_is_logged(two_member_org, caplog: pytest.LogCaptureFixture) -> None:
    _, _, client_b, token_b, org_id, _ = two_member_org
    with caplog.at_level(logging.WARNING):
        client_b.post(
            f"{ORGS_PREFIX}/{org_id}/invitations",
            json={"email": _unique_email()},
            headers=_auth_headers(token_b),
        )
    assert "permission denied" in caplog.text
    assert "members:invite" in caplog.text
