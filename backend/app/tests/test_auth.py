import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.main import app

AUTH_PREFIX = "/api/v1/auth"


@pytest.fixture(autouse=True)
async def _clear_rate_limit_state():
    # Rate limiting is keyed by client IP, and TestClient always reports the
    # same fake IP ("testclient"), so without resetting state between tests
    # a rate-limit test would poison every test that runs after it.
    client = get_redis_client()
    try:
        await client.flushdb()
    finally:
        await client.aclose()
    yield


@pytest.fixture
def client():
    # base_url must be https:// — the refresh cookie is Secure, and httpx's
    # cookie jar silently drops Secure cookies on an http:// base URL.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def _unique_email() -> str:
    return f"user-{uuid.uuid4()}@example.com"


def test_register_returns_created_user(client: TestClient) -> None:
    email = _unique_email()
    response = client.post(
        f"{AUTH_PREFIX}/register", json={"email": email, "password": "correct-horse-1"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert "password" not in body
    assert "password_hash" not in body


def test_register_duplicate_email_is_conflict(client: TestClient) -> None:
    email = _unique_email()
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": "correct-horse-1"})
    response = client.post(
        f"{AUTH_PREFIX}/register", json={"email": email, "password": "another-pass-1"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_full_login_me_refresh_logout_flow(client: TestClient) -> None:
    email = _unique_email()
    password = "correct-horse-battery-1"
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": password})

    login_response = client.post(
        f"{AUTH_PREFIX}/login", json={"email": email, "password": password}
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]
    old_refresh_cookie = login_response.cookies.get("refresh_token")
    assert old_refresh_cookie is not None

    me_response = client.get(
        f"{AUTH_PREFIX}/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == email

    refresh_response = client.post(f"{AUTH_PREFIX}/refresh")
    assert refresh_response.status_code == 200
    new_access_token = refresh_response.json()["access_token"]
    assert new_access_token != access_token
    new_refresh_cookie = refresh_response.cookies.get("refresh_token")
    assert new_refresh_cookie is not None
    assert new_refresh_cookie != old_refresh_cookie

    # Replaying the now-rotated-away old refresh token must fail.
    client.cookies.set("refresh_token", old_refresh_cookie)
    reuse_response = client.post(f"{AUTH_PREFIX}/refresh")
    assert reuse_response.status_code == 401

    # The current (rotated) refresh token still works until logout.
    client.cookies.set("refresh_token", new_refresh_cookie)
    logout_response = client.post(f"{AUTH_PREFIX}/logout")
    assert logout_response.status_code == 204

    post_logout_refresh = client.post(f"{AUTH_PREFIX}/refresh")
    assert post_logout_refresh.status_code == 401


def test_login_wrong_password_rejected(client: TestClient) -> None:
    email = _unique_email()
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": "the-real-password-1"})
    response = client.post(
        f"{AUTH_PREFIX}/login", json={"email": email, "password": "wrong-password-1"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_me_requires_bearer_token(client: TestClient) -> None:
    assert client.get(f"{AUTH_PREFIX}/me").status_code == 401
    bad = client.get(f"{AUTH_PREFIX}/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert bad.status_code == 401


def test_expired_access_token_rejected(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("JWT_ACCESS_TOKEN_TTL_MINUTES", "-1")
    get_settings.cache_clear()
    try:
        from app.core.security import create_access_token

        email = _unique_email()
        register_response = client.post(
            f"{AUTH_PREFIX}/register", json={"email": email, "password": "some-password-1"}
        )
        user_id = uuid.UUID(register_response.json()["id"])
        expired_token = create_access_token(user_id)

        response = client.get(
            f"{AUTH_PREFIX}/me", headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


def test_login_rate_limited_after_repeated_failures(client: TestClient) -> None:
    email = _unique_email()
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": "the-real-password-1"})

    settings = get_settings()
    responses = [
        client.post(f"{AUTH_PREFIX}/login", json={"email": email, "password": "wrong"})
        for _ in range(settings.auth_rate_limit_max_attempts + 1)
    ]

    assert responses[-1].status_code == 429
    assert responses[-1].json()["error"]["code"] == "rate_limited"
    assert all(r.status_code == 401 for r in responses[:-1])


def test_password_never_appears_in_logs(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    password = "this-must-not-be-logged-1"
    email = _unique_email()
    with caplog.at_level(logging.INFO):
        client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": password})
        client.post(f"{AUTH_PREFIX}/login", json={"email": email, "password": password})
        client.post(f"{AUTH_PREFIX}/login", json={"email": email, "password": "wrong-" + password})

    assert password not in caplog.text
