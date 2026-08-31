# Backend Test Coverage (Phase 20)

Measured 2026-08-31 via `make coverage` (`pytest --cov=app --cov-report=term-missing`), full suite: **218 passed, 1 skipped**. Overall: **82%** (4464 statements, 801 missed) across `app/`.

Per SPEC.md §32: "Coverage focus on critical paths, not a vanity percentage." This isn't a gate (no `--cov-fail-under` — see `pyproject.toml`'s `[tool.coverage.report]`), and CI runs it report-only in the `test` job for visibility, not to block merges. The point of this document is to say *where* the real gaps are, not to chase a headline number.

## Critical-path modules

| Module (service layer) | Coverage | Note |
|---|---|---|
| `core/security.py` (password hashing, JWT) | 97% | Solid. |
| `core/tenancy.py` (RLS context) | 100% | Solid — this is the one thing that must never regress silently. |
| `modules/auth/service.py` | **46%** | Real gap — see below. |
| `modules/auth/router.py` | 74% | Login/register/refresh happy paths covered; some error branches aren't. |
| `modules/orgs/dependencies.py` (RBAC `require_permission`) | **66%** | Real gap — see below. |
| `modules/orgs/service.py` | **43%** | Real gap — see below. |
| `modules/search/service.py` | 98% | Solid. |
| `modules/assistant/service.py` | 84% | Solid; gaps are mostly cost-guard edge branches. |
| `modules/agents/service.py` | **64%** | Real gap — see below. |
| `modules/workflows/service.py` | **56%** | Real gap — see below. |
| `modules/documents/service.py` | 80% | Solid. |
| `modules/ingestion/*` | 86–100% | Solid across extraction/chunking/embeddings/pipeline. |

## Real gaps worth calling out

- **`orgs/service.py` (43%)**: the happy paths (create org, invite, accept, list members) are covered via existing integration tests hitting the router; what's missed is mostly custom-role management, invitation edge cases (expired/already-accepted/wrong-email), and membership removal — all real authorization-adjacent code, worth a dedicated pass.
- **`orgs/dependencies.py` (66%)**: `require_permission`'s deny branches (missing membership, wrong role, custom role without the permission) are under-exercised relative to its allow branches — this is *the* RBAC enforcement point (SPEC.md §14–15), so this is the single highest-value gap to close next.
- **`auth/service.py` (46%)**: refresh-token rotation edge cases (revoked, expired, reused) and a few registration-validation branches aren't hit directly (some are exercised indirectly through router tests but the coverage tool only credits the service-layer line when a service-level test calls it directly).
- **`agents/service.py` (64%)** / **`workflows/service.py` (56%)**: both have their core execution-loop happy paths well covered (guardrails, tool-calling, DAG execution, retries are all under dedicated tests), but a number of admin-y branches (agent/workflow update, listing edge cases, version-diffing) are thinner.

None of these are silent security holes — the RLS/ACL/tenant-isolation paths specifically called out in SPEC.md §42's "always-on acceptance gates" are all at or near 100% (`core/tenancy.py` 100%, `search/service.py` 98%, the dedicated `test_tenant_isolation.py` suite). These are ordinary line-coverage gaps in secondary/edge-case branches, tracked here as backlog rather than backfilled in this phase (Phase 20's scope was measuring and documenting, not an unbounded test-writing pass across every module).

## Not a concern (expected low coverage)

- `app/workers/run.py` (0%): the Arq worker process entrypoint — thin `if __name__` wiring, not unit-testable in the normal sense; exercised in practice by `docker compose up worker` actually running.
- `ai/providers.py` (63%), `notifications/providers.py` (36%), `billing/stripe_client.py` (59%): the real Anthropic/OpenAI/Ollama/SMTP/Stripe network-calling code paths. Deliberately never exercised by automated tests (CLAUDE.md §6/§7 — never call a real paid/external API in tests); every test mocks these at the boundary instead. Low coverage here is by design, not a gap.

## Reproducing

```bash
make coverage
```
