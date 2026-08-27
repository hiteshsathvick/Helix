"""Eval harness tests (SPEC.md §41 Phase 11: "eval harness runs in CI on a
fixed dataset; regression thresholds").

Retrieval scoring makes no LLM call, so it always runs for real, for free.
Answer-quality scoring makes a real LLM call per eval case — kept opt-in
(RUN_LIVE_EVALS=1 + a real ANTHROPIC_API_KEY) so CI stays free and
deterministic by default, matching how every other test in this suite
mocks `ai_service.stream_completion` rather than calling a real provider.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import session_factory
from app.core.redis import get_redis_client
from app.core.tenancy import set_tenant_context
from app.main import app
from app.modules.ai.evals.dataset import DOCUMENTS
from app.modules.ai.evals.runner import (
    MIN_GROUNDED_RATE,
    MIN_HIT_RATE,
    MIN_MRR,
    run_answer_quality_eval,
    run_retrieval_eval,
)
from app.modules.ingestion.pipeline import run_ingestion

AUTH_PREFIX = "/api/v1/auth"
ORGS_PREFIX = "/api/v1/orgs"

_RUN_LIVE_EVALS = os.getenv("RUN_LIVE_EVALS") == "1" and bool(os.getenv("ANTHROPIC_API_KEY"))


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


async def _seed_eval_org(
    client: TestClient,
) -> tuple[uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
    email = _unique_email()
    password = "a-strong-password-1"
    client.post(f"{AUTH_PREFIX}/register", json={"email": email, "password": password})
    token = client.post(f"{AUTH_PREFIX}/login", json={"email": email, "password": password}).json()[
        "access_token"
    ]
    user_id = uuid.UUID(client.get(f"{AUTH_PREFIX}/me", headers=_auth_headers(token)).json()["id"])
    org_id = uuid.UUID(
        client.post(
            ORGS_PREFIX,
            json={"name": "Eval Org", "slug": f"eval-org-{uuid.uuid4().hex[:8]}"},
            headers=_auth_headers(token),
        ).json()["id"]
    )

    doc_ids: dict[str, uuid.UUID] = {}
    async with session_factory() as db:
        for doc in DOCUMENTS:
            document_id = uuid.UUID(
                client.post(
                    f"{ORGS_PREFIX}/{org_id}/documents",
                    files={"file": (f"{doc.key}.txt", doc.content.encode(), "text/plain")},
                    headers=_auth_headers(token),
                ).json()["id"]
            )
            doc_ids[doc.key] = document_id
            await run_ingestion(db, org_id, document_id)

    return org_id, user_id, doc_ids


@pytest.mark.asyncio
async def test_retrieval_eval_meets_regression_thresholds(client: TestClient) -> None:
    org_id, user_id, doc_ids = await _seed_eval_org(client)

    async with session_factory() as db:
        await set_tenant_context(db, org_id)
        report = await run_retrieval_eval(db, org_id, user_id, doc_ids)

    assert report.n_cases == len(doc_ids)
    assert report.hit_rate >= MIN_HIT_RATE, f"retrieval hit-rate regressed: {report.hit_rate}"
    assert report.mrr >= MIN_MRR, f"retrieval MRR regressed: {report.mrr}"


@pytest.mark.skipif(
    not _RUN_LIVE_EVALS,
    reason="opt-in live eval: set RUN_LIVE_EVALS=1 and a real ANTHROPIC_API_KEY to run "
    "(makes real, billed LLM calls — never runs automatically in CI)",
)
@pytest.mark.asyncio
async def test_answer_quality_eval_meets_regression_threshold(client: TestClient) -> None:
    org_id, user_id, doc_ids = await _seed_eval_org(client)

    async with session_factory() as db:
        await set_tenant_context(db, org_id)
        report = await run_answer_quality_eval(db, org_id, user_id, doc_ids)

    assert report.n_cases == len(doc_ids)
    assert (
        report.grounded_rate >= MIN_GROUNDED_RATE
    ), f"answer-quality grounded-rate regressed: {report.grounded_rate}"
