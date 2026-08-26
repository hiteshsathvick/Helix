# Helix

Multi-tenant, AI-native enterprise platform. See [SPEC.md](SPEC.md) for the full spec and [CLAUDE.md](CLAUDE.md) for the operating rules this repo is built under.

## Quickstart

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000/health
- Frontend: http://localhost:3000

## Development

```bash
make up             # docker compose up --build
make test           # run backend tests
make test-frontend  # run frontend component tests (vitest)
make test-e2e       # run Playwright e2e tests (needs `make up` running first)
make lint           # ruff + mypy + eslint + tsc
make migrate        # alembic upgrade head
make seed           # seed demo data (added once orgs/documents phases land)
```

## Status

Phase 9 (frontend foundation & core UI) — see `SPEC.md` §41 for the roadmap. Phases 0–8 (backend foundation through auth, orgs, RBAC, documents, ingestion, and hybrid search) are complete; later domain modules under `backend/app/modules/` remain structural stubs until their phase lands.
