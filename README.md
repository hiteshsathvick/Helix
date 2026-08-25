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
make up        # docker compose up --build
make test       # run backend tests
make lint       # ruff + mypy + eslint
make migrate    # alembic upgrade head
make seed       # seed demo data (added once orgs/documents phases land)
```

## Status

Phase 0 (repository & architecture setup) — see `SPEC.md` §41 for the roadmap. Domain modules under `backend/app/modules/` are structural stubs; functionality is added phase by phase.
