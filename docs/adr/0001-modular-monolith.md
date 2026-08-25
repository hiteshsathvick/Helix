# ADR 0001: Modular monolith with domain-module boundaries

## Context

Helix (SPEC.md §1, §8) needs to support many domains (auth, orgs, documents, ingestion, search, assistant, agents, workflows, connectors, notifications, billing, analytics, audit, public API) built out incrementally by a single engineer over 6–12+ months, while leaving a credible path to extract services later (SPEC.md §40) without a rewrite.

## Decision

Build one FastAPI application (the "backend") composed of domain modules under `backend/app/modules/<domain>/`, each owning its own `router.py`, `service.py`, `models.py`, `schemas.py`, and `tests/`. Modules communicate only through each other's public service interfaces or via domain events on the queue — never by importing another module's models or querying its tables directly (CLAUDE.md §3). The backend and its worker process share a single Docker image with two entrypoints (`app.main:app` for the API, `app.workers.run` for the worker), per SPEC.md §9 and §34.

The frontend is a separate Next.js app (`frontend/`) consuming the backend's OpenAPI-generated contract, mirroring the module boundary with `src/features/<domain>/`.

## Consequences

- Module directories are created empty in Phase 0 as structural placeholders, so later phases add code into an already-agreed shape instead of restructuring.
- A module boundary violation (direct cross-module table access) is a code-review-time defect, not just a style preference — it is what keeps future service extraction possible.
- Local development is a single `docker compose up`; there is no per-service deploy story yet, by design (SPEC.md §3 Non-Goals — no premature microservices).
