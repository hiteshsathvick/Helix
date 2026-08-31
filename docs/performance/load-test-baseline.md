# Load Test Baseline (Phase 20)

Real runs against the local `docker compose` stack on 2026-08-31 (single api container with `--reload`, single worker, Postgres/Redis/MinIO all in Docker on one Windows/WSL2 development machine — **not** a production-shaped deployment; see caveats below). Scripts: `infra/load/{search,assistant,ingestion}.js`. Tool: k6, run via `docker run --rm -i --network helix_default -e BASE_URL=http://api:8000 grafana/k6 run - < infra/load/<script>.js`.

## Results

| Target (SPEC.md §7) | Script | Result | Met? |
|---|---|---|---|
| p95 search < 400ms | `search.js` (5 VUs, 30s) | 100% success (0 failed of ~280 requests); **p95 = 696ms** | ✗ locally (see caveats) |
| Assistant first token < 2s | `assistant.js` (5 VUs, 20s, mock provider) | 100% success; avg full-response 1.07s, p95 = 1.41s | Roughly, with a caveat (see below) |
| Ingestion ≥ 50 docs/min/worker | `ingestion.js` (3 VUs, 60s) | 100% success; 75 docs ingested in ~60s across 3 concurrent VUs / 1 worker ≈ **25 docs/min/worker** | ✗ |

## A real bug this surfaced, not just numbers

The first `ingestion.js` run failed almost every request (`sqlalchemy.exc.MultipleResultsFound`). `documents/service.py::get_or_create_manual_source` was a classic check-then-insert race with no DB-level constraint: concurrent first uploads to a brand-new org could each insert a "manual" `Source` row. Fixed in the same PR:
- Migration `11400a085f70`: a partial unique index (`org_id`, `WHERE type = 'manual' AND deleted_at IS NULL`), after soft-deleting any duplicates already created by the race.
- `get_or_create_manual_source`: catches the resulting `IntegrityError`, rolls back, and re-queries. `upload_document` was also adjusted to capture `uploader.id` *before* calling it — a plain `db.rollback()` expires every object already loaded in that session (including the `User` loaded earlier by the auth dependency), and reading a lazy attribute off it afterward could itself fail under the same concurrent load. (A SAVEPOINT via `db.begin_nested()` looked like the more surgical fix and was tried first, but consistently left the session in `PendingRollbackError` afterward under this SQLAlchemy/asyncpg combination — the plain rollback, with tenant context re-established, is what actually works here.)

After the fix: 0 failures across all three scripts, confirmed by 5 repeated runs of the new regression test (`test_documents.py::test_get_or_create_manual_source_survives_a_concurrent_race`) plus a full k6 re-run (see table above).

## Caveats on the numbers themselves

- **Single dev-mode `uvicorn --reload` process, not a production ASGI deployment** (no multi-worker Gunicorn/uvicorn setup, no separate read replica, no connection pooling tuning) — the whole point of a *baseline*, not a verdict on whether Helix can hit its NFRs in production. Real perf tuning is explicitly Phase 23's job (SPEC.md §39/40); this phase's job was only to measure and record honestly.
- Everything ran on one Windows/WSL2 machine that was also running Docker Desktop, this session's own tooling, and (for the assistant/ingestion runs) the `worker` container concurrently — noisy-neighbor effects on this specific host are real and not representative of a dedicated environment.
- `assistant.js` uses `AI_DEFAULT_PROVIDER=mock` (Phase 20's deterministic zero-cost provider, `ai/providers.py`) so the numbers measure Helix's own streaming/request-handling path, not a real Anthropic API call's latency — a real-provider run would look different (and cost money per request, which is exactly why this baseline doesn't do that).
- k6's core `http` module buffers the whole SSE response rather than exposing per-frame arrival times, so the assistant numbers are "time to full answer," not strictly "time to first token" (documented in `assistant.js` itself).

## Reproducing

```bash
docker compose up -d --build
# assistant.js needs AI_DEFAULT_PROVIDER=mock in .env before the line above --
# revert it afterward, it must never be the default for a real deployment.
docker run --rm -i --network helix_default -e BASE_URL=http://api:8000 grafana/k6 run - < infra/load/search.js
docker run --rm -i --network helix_default -e BASE_URL=http://api:8000 grafana/k6 run - < infra/load/assistant.js
docker run --rm -i --network helix_default -e BASE_URL=http://api:8000 grafana/k6 run - < infra/load/ingestion.js
```
