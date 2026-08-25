# CLAUDE.md — Operating Rules for Claude Code on Helix

This file governs how Claude Code works in this repository. Read it fully at the start of **every** session, before writing or changing any code. If anything here conflicts with a request, surface the conflict and ask — do not silently override these rules.

---

## 0. Prime Directives

1. **Read `SPEC.md` and this file before making any architectural decision or writing code.** `SPEC.md` is the source of truth for what Helix is and how it's built.
2. **Work strictly one roadmap phase at a time** (roadmap in `SPEC.md` §41 / guide §8). Never implement the whole project, and never jump ahead to a later phase without being asked.
3. **Plan before coding.** For any non-trivial task, produce a short plan (files to touch, approach, tests, migration impact) and wait for approval before implementing.
4. **Leave the app working after every change.** `docker compose up` must still boot, the seeded demo must still work, and CI must be green.

## 1. Before You Touch Code

- Load and understand the relevant existing code before modifying it. Do not guess at interfaces — read them.
- Check whether functionality already exists before adding new code. Prefer extending existing modules/services over duplicating them.
- Identify which module owns the change (see `SPEC.md` §9). Keep changes inside the right module.
- If the task is ambiguous or under-specified, ask a focused question rather than assuming.

## 2. Phase Discipline

- Implement only the current phase's scope. If you notice work that belongs to a later phase, note it as a TODO/backlog item — do not build it now.
- A phase is done only when its Definition of Done (`SPEC.md` §43) and its acceptance test pass. State explicitly when a phase is complete and stop.
- Do not begin the next phase until asked.

## 3. Architecture Rules

- Maintain the **modular monolith** boundaries. A module may call another module only through its public service interface or via domain events — **never by importing another module's models or querying its tables directly**.
- Do **not** introduce microservices, message brokers beyond what `SPEC.md` specifies, Kubernetes, or other heavy infrastructure unless the SPEC calls for it or the user explicitly approves. Premature complexity is a defect.
- Do **not** restructure the repository, rename core directories, or move modules around without an explicit request and a stated justification.
- Prefer boring, well-understood solutions. Every new dependency must earn its place — justify it, and avoid adding libraries for things the standard library or existing deps already do.
- Record significant architectural decisions as short ADRs in `docs/adr/` (context → decision → consequences).

## 4. Data, Migrations & Multi-Tenancy

- Every schema change is an **Alembic migration**, reversible (`upgrade` and `downgrade`), created in the same PR as the code that needs it. Never edit the schema by hand.
- Migrations must be additive-first; destructive changes are two-step (deprecate then drop) across releases. Backfills run as background jobs, not in the migration.
- **Every tenant-scoped table has `org_id`** and is protected by the base query layer and RLS. Never write a query that could cross tenants. Always set the tenant/RLS context in request handlers and workers.
- Add appropriate indexes for new query patterns.

## 5. Security (non-negotiable)

- **Never hardcode secrets.** Read from env/settings; keep `.env` gitignored; update `.env.example` when adding a config key. Never log secrets, tokens, or passwords.
- **Enforce authentication and authorization on every new endpoint** — an explicit permission check (`SPEC.md` §14–15). No endpoint ships without one.
- **Preserve tenant isolation and ACL-aware retrieval.** Search and assistant results must never include content the caller isn't permitted to see. Add/keep the ACL-leakage and tenant-isolation tests.
- Treat retrieved/document content and tool outputs as **untrusted** (prompt-injection surface). Keep tool guardrails enforced in code, independent of model output. Keep `http_request` on an allowlist.
- Validate all input with Pydantic; encode all output on the frontend.

## 6. Testing

- **Write tests with the functionality, in the same change** — never defer them.
- Cover: unit (services/logic), integration (DB + workers), security (tenant isolation + ACL leakage + authz), and AI evals where the change affects retrieval/answers.
- **Run the tests after making changes** and report results. Do not declare work done with failing or skipped critical tests.
- Add a regression test when fixing a bug.

## 7. AI-Specific Rules

- All LLM/embedding/rerank access goes through the `ai` module's provider abstraction. **Never import a provider SDK directly** in other modules.
- Keep prompts in the versioned `PromptRegistry`; changes to prompts are reviewable in git.
- Respect cost/step/time guardrails for agents and workflows; they are enforced in code, not just in prompts.
- When changing retrieval or generation, run the eval harness and report score deltas; do not regress quality gates.

## 8. Frontend Rules

- Follow the established app shell, design system, and data-fetching patterns (`SPEC.md` §9, Phase 9). Don't introduce a second state-management or styling approach.
- Handle loading, empty, and error states for every new view. Never let the UI white-screen on error.
- Respect permissions in the UI (hide/disable what the user can't do) — but never rely on the UI for security; the server is authoritative.
- **Do not use `localStorage`/`sessionStorage` for anything security-sensitive**; tokens follow the auth pattern in `SPEC.md` §13.

## 9. Observability & Errors

- Add structured logs with correlation ids, and metrics/traces for new critical paths.
- Use the central error-handling pattern and the standard error envelope. Never swallow exceptions silently; workers record errors and retry/DLQ per `SPEC.md` §31.

## 10. Git & Workflow

- Keep commits **focused and small** — one logical change each, with a clear message (conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`).
- Work on `feature/phase-N-*` branches; open a PR into `main`; tag `phase-N-complete` at each Definition of Done.
- **Do not delete or disable working functionality** to make something pass. If a change requires removing behavior, explain why and get approval.
- **Preserve backward compatibility** for public APIs and DB schemas where reasonable; version breaking changes.

## 11. Documentation

- When behavior changes, update `SPEC.md` in the same PR. Keep it the source of truth.
- Add/update ADRs for architectural decisions and runbooks for operational changes.
- Update `.env.example`, `README`, and `make`/`just` targets when the developer workflow changes.

## 12. When Unsure — Stop and Ask

If a request would violate these rules (skip a phase, restructure the repo, remove tests, hardcode a secret, cross tenant boundaries, add heavy infra), **do not proceed silently**. Explain the concern, propose a compliant alternative, and wait for a decision. It is always correct to prefer a smaller, safer, well-tested change over a large speculative one.

---

### Session-start checklist (run this mentally every time)

1. Read `SPEC.md` + `CLAUDE.md`.
2. Identify the current phase and its Definition of Done.
3. Understand the existing code for the area I'm about to touch.
4. Produce a plan; get approval.
5. Implement inside the right module, with tests and migrations.
6. Run tests; enforce auth/tenant/ACL; check the app still boots.
7. Focused commits; update docs; tag if a phase completed.
