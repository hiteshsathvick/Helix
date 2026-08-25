import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.redis import get_redis_client
from app.main import app

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


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def _unique_email() -> str:
    return f"user-{uuid.uuid4()}@example.com"


def _register_and_login(
    client: TestClient, email: str | None = None, password: str = "a-strong-password-1"
) -> tuple[str, str]:
    """Returns (email, access_token). Uses a fresh TestClient-scoped session
    so each caller's refresh cookie doesn't clobber another's within the
    same test."""
    email = email or _unique_email()
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": password})
    login_response = client.post(
        f"{AUTH_PREFIX}/login", json={"email": email, "password": password}
    )
    return email, login_response.json()["access_token"]


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_create_org_makes_creator_a_member(client: TestClient) -> None:
    _, token = _register_and_login(client)
    response = client.post(
        ORGS_PREFIX,
        json={"name": "Acme Corp", "slug": f"acme-{uuid.uuid4().hex[:8]}"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 201
    org_id = response.json()["id"]

    members = client.get(f"{ORGS_PREFIX}/{org_id}/members", headers=_auth_headers(token))
    assert members.status_code == 200
    assert len(members.json()) == 1


def test_duplicate_slug_is_conflict(client: TestClient) -> None:
    _, token = _register_and_login(client)
    slug = f"dup-{uuid.uuid4().hex[:8]}"
    client.post(ORGS_PREFIX, json={"name": "First", "slug": slug}, headers=_auth_headers(token))
    response = client.post(
        ORGS_PREFIX, json={"name": "Second", "slug": slug}, headers=_auth_headers(token)
    )
    assert response.status_code == 409


def test_full_invite_accept_lifecycle_and_tenant_isolation() -> None:
    # Two independent TestClients so each user's refresh cookie stays isolated.
    with (
        TestClient(app, base_url="https://testserver") as client_a,
        TestClient(app, base_url="https://testserver") as client_b,
    ):
        email_a, token_a = _register_and_login(client_a)
        email_b, token_b = _register_and_login(client_b)

        create_response = client_a.post(
            ORGS_PREFIX,
            json={"name": "Org A", "slug": f"org-a-{uuid.uuid4().hex[:8]}"},
            headers=_auth_headers(token_a),
        )
        org_id = create_response.json()["id"]

        invite_response = client_a.post(
            f"{ORGS_PREFIX}/{org_id}/invitations",
            json={"email": email_b},
            headers=_auth_headers(token_a),
        )
        assert invite_response.status_code == 201
        raw_token = invite_response.json()["token"]

        accept_response = client_b.post(
            f"{INVITATIONS_PREFIX}/{raw_token}/accept", headers=_auth_headers(token_b)
        )
        assert accept_response.status_code == 200
        token_b = accept_response.json()["access_token"]

        members_response = client_b.get(
            f"{ORGS_PREFIX}/{org_id}/members", headers=_auth_headers(token_b)
        )
        assert members_response.status_code == 200
        member_emails = {m["email"] for m in members_response.json()}
        assert member_emails == {email_a, email_b}

        # A second org that B has nothing to do with must stay invisible.
        other_org = client_a.post(
            ORGS_PREFIX,
            json={"name": "Org C", "slug": f"org-c-{uuid.uuid4().hex[:8]}"},
            headers=_auth_headers(token_a),
        )
        other_org_id = other_org.json()["id"]
        leak_check = client_b.get(
            f"{ORGS_PREFIX}/{other_org_id}/members", headers=_auth_headers(token_b)
        )
        assert leak_check.status_code == 404


def test_reusing_an_already_accepted_invitation_fails() -> None:
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

        first = client_b.post(
            f"{INVITATIONS_PREFIX}/{raw_token}/accept", headers=_auth_headers(token_b)
        )
        assert first.status_code == 200

        second = client_b.post(
            f"{INVITATIONS_PREFIX}/{raw_token}/accept", headers=_auth_headers(token_b)
        )
        assert second.status_code == 404


def test_accepting_invitation_with_wrong_account_is_forbidden(client: TestClient) -> None:
    _, token_a = _register_and_login(client)
    org_id = client.post(
        ORGS_PREFIX,
        json={"name": "Org A", "slug": f"org-a-{uuid.uuid4().hex[:8]}"},
        headers=_auth_headers(token_a),
    ).json()["id"]

    raw_token = client.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": "someone-else@example.com"},
        headers=_auth_headers(token_a),
    ).json()["token"]

    # token_a's own account does not match the invited email.
    response = client.post(
        f"{INVITATIONS_PREFIX}/{raw_token}/accept", headers=_auth_headers(token_a)
    )
    assert response.status_code == 403


def test_switch_org_rejected_for_non_member(client: TestClient) -> None:
    _, token_a = _register_and_login(client)
    org_id = client.post(
        ORGS_PREFIX,
        json={"name": "Org A", "slug": f"org-a-{uuid.uuid4().hex[:8]}"},
        headers=_auth_headers(token_a),
    ).json()["id"]

    with TestClient(app, base_url="https://testserver") as outsider_client:
        _, token_b = _register_and_login(outsider_client)
        response = outsider_client.post(
            f"{ORGS_PREFIX}/{org_id}/switch", headers=_auth_headers(token_b)
        )
        assert response.status_code == 404


def test_switch_org_updates_active_org_claim(client: TestClient) -> None:
    _, token = _register_and_login(client)
    org_a = client.post(
        ORGS_PREFIX,
        json={"name": "Org A", "slug": f"org-a-{uuid.uuid4().hex[:8]}"},
        headers=_auth_headers(token),
    ).json()
    org_b = client.post(
        ORGS_PREFIX,
        json={"name": "Org B", "slug": f"org-b-{uuid.uuid4().hex[:8]}"},
        headers=_auth_headers(token),
    ).json()

    switch_response = client.post(
        f"{ORGS_PREFIX}/{org_b['id']}/switch", headers=_auth_headers(token)
    )
    assert switch_response.status_code == 200
    new_token = switch_response.json()["access_token"]
    assert new_token != token

    me_orgs = client.get(ORGS_PREFIX, headers=_auth_headers(new_token))
    assert {o["id"] for o in me_orgs.json()} == {org_a["id"], org_b["id"]}
