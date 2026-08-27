import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.errors import QuotaExceededError
from app.core.redis import get_redis_client
from app.main import app
from app.modules.ai import cost_guard
from app.modules.ai import service as ai_service
from app.modules.ai.prompts import ASSISTANT_SYSTEM_PROMPT_CURRENT, get_prompt
from app.modules.ai.providers import compute_cost

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


async def _fake_stream_completion(system, messages, max_tokens, *, provider=None, model=None):
    yield ai_service.TextDelta("An answer.")
    yield ai_service.UsageInfo(input_tokens=100, output_tokens=20)


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    # Same rationale as test_assistant.py: never let a test hit a real
    # provider — costs money and makes CI nondeterministic.
    monkeypatch.setattr(ai_service, "stream_completion", _fake_stream_completion)


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


# --- unit: provider pricing, prompt registry, cost guard ---


def test_compute_cost_known_model():
    cost = compute_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(12.0)


def test_compute_cost_unknown_model_is_free():
    assert compute_cost("some-unpriced-model", input_tokens=1000, output_tokens=1000) == 0.0


def test_prompt_registry_renders_current_version():
    rendered = ASSISTANT_SYSTEM_PROMPT_CURRENT.render(context="hello")
    assert "hello" in rendered
    assert get_prompt("assistant_system", 1) is ASSISTANT_SYSTEM_PROMPT_CURRENT


def test_prompt_registry_unknown_version_raises():
    with pytest.raises(ValueError, match="unknown prompt"):
        get_prompt("assistant_system", 999)


def test_cost_guard_allows_when_under_cap():
    cost_guard.enforce_cost_cap(spent_usd=1.0, cap_usd=5.0)  # must not raise


def test_cost_guard_allows_when_uncapped():
    cost_guard.enforce_cost_cap(spent_usd=1_000_000.0, cap_usd=None)  # must not raise


def test_cost_guard_blocks_when_at_or_over_cap():
    with pytest.raises(QuotaExceededError):
        cost_guard.enforce_cost_cap(spent_usd=5.0, cap_usd=5.0)


# --- integration: org AI config endpoint ---


def test_get_ai_config_defaults_to_global_settings(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)

    response = client.get(f"{ORGS_PREFIX}/{org_id}/ai-config", headers=_auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "anthropic"
    assert body["monthly_cost_cap_usd"] is None


def test_owner_can_update_ai_config(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)

    update = client.put(
        f"{ORGS_PREFIX}/{org_id}/ai-config",
        json={"provider": "openai", "model": "gpt-4o-mini", "monthly_cost_cap_usd": 10.0},
        headers=_auth_headers(token),
    )
    assert update.status_code == 200
    assert update.json() == {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "monthly_cost_cap_usd": 10.0,
    }

    refetched = client.get(f"{ORGS_PREFIX}/{org_id}/ai-config", headers=_auth_headers(token))
    assert refetched.json()["provider"] == "openai"


def test_update_ai_config_rejects_unknown_provider(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)

    response = client.put(
        f"{ORGS_PREFIX}/{org_id}/ai-config",
        json={"provider": "not-a-real-provider"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422


def test_member_cannot_update_ai_config(client: TestClient) -> None:
    owner_token, org_id = _register_login_and_create_org(client)
    member_email = _unique_email()
    member_password = "a-strong-password-1"
    client.post(
        f"{AUTH_PREFIX}/register", json={"email": member_email, "password": member_password}
    )
    member_token = client.post(
        f"{AUTH_PREFIX}/login", json={"email": member_email, "password": member_password}
    ).json()["access_token"]

    invite = client.post(
        f"{ORGS_PREFIX}/{org_id}/invitations",
        json={"email": member_email},
        headers=_auth_headers(owner_token),
    ).json()
    client.post(
        f"/api/v1/invitations/{invite['token']}/accept",
        headers=_auth_headers(member_token),
    )

    response = client.put(
        f"{ORGS_PREFIX}/{org_id}/ai-config",
        json={"provider": "openai"},
        headers=_auth_headers(member_token),
    )

    assert response.status_code == 403


# --- integration: cost cap blocks further assistant queries ---


def test_assistant_query_blocked_once_org_cost_cap_is_reached(client: TestClient) -> None:
    token, org_id = _register_login_and_create_org(client)
    # Mocked usage (100 in / 20 out on claude-sonnet-5, the default model)
    # costs (100*2.0 + 20*10.0) / 1_000_000 = 0.0004 per query — a cap set
    # below that is exceeded by the very first query.
    client.put(
        f"{ORGS_PREFIX}/{org_id}/ai-config",
        json={"monthly_cost_cap_usd": 0.0001},
        headers=_auth_headers(token),
    )

    first = client.post(
        f"{ORGS_PREFIX}/{org_id}/assistant/query",
        json={"query": "hello"},
        headers=_auth_headers(token),
    )
    assert first.status_code == 200

    second = client.post(
        f"{ORGS_PREFIX}/{org_id}/assistant/query",
        json={"query": "hello again"},
        headers=_auth_headers(token),
    )
    assert second.status_code == 402
    assert second.json()["error"]["code"] == "quota_exceeded"
