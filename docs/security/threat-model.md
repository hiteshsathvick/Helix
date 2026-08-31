# Helix Threat Model

Written for Phase 19 (SPEC.md §29, roadmap §41 Phase 19). DoD: every risk below maps to a control and a test. This is a living document — update it in the same PR whenever a change adds a new trust boundary, a new tool/connector, or changes how a control works (CLAUDE.md §11).

## Assets

- **Tenant data**: organizations, documents, chunks, conversations, agent/workflow runs, audit logs — everything scoped by `org_id`.
- **Credentials & secrets**: password hashes, JWT signing keys, refresh/invitation/API-key tokens, connector OAuth tokens, webhook secrets, Stripe keys.
- **LLM/agent execution**: prompts, tool-calling loop, agent/workflow guardrail budgets (steps, cost, time).
- **Inbound integration surface**: public API, outbound webhooks, inbound workflow-trigger webhooks, connector OAuth callbacks.

## Actors

- **External unauthenticated attacker** — internet, no credentials.
- **Authenticated member of another org** — a real account, wrong tenant.
- **Malicious or compromised org member** — valid credentials, acting inside their own org's permissions (or trying to exceed them).
- **Malicious ingested/retrieved content** — a document, connector item, or tool response an attacker controls the text of, consumed by the LLM.
- **Compromised or malicious webhook/HTTP target** — the far end of an outbound webhook delivery or an agent's `http_request` call.

## Risks → Controls → Tests

| # | Risk | Actor | Control | Test |
|---|------|-------|---------|------|
| 1 | Cross-tenant data leakage — a query returns another org's rows | Authenticated member of another org | Postgres RLS (`app.current_org` session var) as defense-in-depth behind the app-layer `org_id` filter on every query (SPEC.md §16); `set_tenant_context` called on every request and worker job | `backend/app/tests/test_tenant_isolation.py` |
| 2 | ACL leakage — search/assistant/agent surfaces content the user isn't permitted to see | Authenticated member, wrong document ACL | `document_acls`-joined filtering in `search/service.py`, reused as-is by the assistant and the `search` agent tool (SPEC.md §18 step 2) | `test_assistant.py::test_assistant_does_not_leak_citations_across_tenants`, ACL cases in `test_search.py` |
| 3 | Prompt injection — text embedded in a retrieved chunk overrides the assistant's instructions or exfiltrates the system prompt | Malicious ingested content | System/context separation in `ai/prompts.py` — untrusted content is confined to the `{context}` slot of a fixed template, never concatenated into the instruction text; "answer only from context" instruction | `test_ai.py::test_assistant_prompt_isolates_untrusted_context_from_instructions` |
| 4 | SSRF via agent tools — `http_request` used to reach internal/cloud-metadata hosts | Malicious/compromised org member steering an agent, or injected content steering the model | Default-deny host allowlist (`agent_http_allowlist`, empty = refuse everything), method restricted to GET/POST, response body truncated (SPEC.md §29) | `test_agents.py::test_http_request_tool_denies_by_default`, `::test_http_request_tool_allows_allowlisted_host` |
| 5 | SSRF via connectors | Malicious/compromised org member | Separate default-deny `connector_web_allowlist` | connector web-fetch tests in `test_connectors.py` |
| 6 | Agent/workflow runaway cost or loop | Malicious/compromised org member, or a buggy workflow graph | Hard-enforced (not just prompted) `agent_max_steps`, `agent_run_timeout_seconds`, `agent_max_run_cost_usd`; `workflow_run_max_steps`, `workflow_run_timeout_seconds` (SPEC.md §19–20) | run-guardrail tests in `test_agents.py`/`test_workflows.py` |
| 7 | Credential/token exposure | External attacker with DB/log access | Argon2 password hashes; refresh/invitation/API-key tokens stored as SHA-256 hashes of high-entropy opaque tokens, never the raw value (`core/security.py`); connector OAuth tokens encrypted at rest with Fernet | `test_auth.py::test_password_never_appears_in_logs`; hash-not-plaintext assertions in `test_auth.py`/`test_api.py`/`test_connectors.py` |
| 8 | Shipping local-dev secret defaults into a real environment | Anyone who can reach a misconfigured deployment | Startup guard (`core/secrets_guard.py`) refuses to boot when `environment != "local"` and `jwt_signing_keys`/`connector_encryption_key` are still their committed defaults | `test_secrets_startup_guard.py` |
| 9 | Outbound webhook forgery — a receiver can't verify a delivery is really from Helix | Compromised/malicious webhook receiver, or a spoofed sender | `X-Helix-Signature: sha256=<hmac>` over the raw body (Phase 18) | webhook signing tests in `test_api.py` |
| 10 | Inbound workflow-webhook abuse — brute-forcing the per-workflow secret, or triggering excessive runs | External unauthenticated attacker | Per-workflow opaque secret (`verify_webhook_secret`) plus a per-client-IP rate limit on the endpoint itself, checked before the secret (`workflow_webhook_rate_limit_*`) | rate-limit test for `trigger_via_webhook` in `test_workflows.py` |
| 11 | Public API key abuse / credential stuffing | External attacker, or a leaked key | Keys stored hashed, scoped, per-key rate limit independent of any org quota (`enforce_api_key_rate_limit`, Phase 18) | `test_api.py` key-scoping/rate-limit tests |
| 12 | Login brute-forcing | External attacker | Per-IP fixed-window rate limit on `/auth/login` | `test_auth.py::test_login_rate_limited_after_repeated_failures` |
| 13 | DoS / cost abuse on authenticated LLM-cost-bearing endpoints (assistant query, agent run, workflow trigger) | Authenticated member (or a compromised session) | Per-user rate limits added in Phase 19 (`enforce_user_rate_limit`), independent of the per-run cost/step caps in #6 | rate-limit tests in `test_assistant.py`, `test_agents.py`, `test_workflows.py` |
| 14 | Clickjacking / MIME sniffing / referrer leakage on API responses | External attacker | `SecurityHeadersMiddleware` (Phase 19): `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy: default-src 'none'`, HSTS outside local | `test_security_headers.py` |
| 15 | Cross-origin credential theft via an overly permissive CORS policy | External attacker's page, browser context | `CORSMiddleware` restricted to `settings.frontend_url` with an explicit method/header allowlist (Phase 19), not `*` | manual verification (`curl -i` OPTIONS preflight); covered indirectly by e2e tests still passing against the real frontend origin |
| 16 | Known-vulnerable dependency shipped to production | External attacker exploiting a published CVE | `pip-audit` + `npm audit` in CI (Phase 19, report-only — see backlog below); Dependabot weekly PRs for pip/npm/github-actions/docker | CI `dependency-scan` job |
| 17 | Known-vulnerable OS/app layer in the built container image | External attacker | Trivy scan of both built images in CI (Phase 19, report-only — see backlog below) | CI `build` job's Trivy steps |
| 18 | PII in logs | Anyone with log access | Structured JSON logging with only `request_id`/`level`/`logger`/`message` fields (`core/logging.py`) — no request/response bodies logged by default; explicit test that a submitted password never appears in captured logs | `test_auth.py::test_password_never_appears_in_logs` |

## Known accepted risks / backlog

- **`pip-audit` (2026-08-31 run) found real CVEs in 5 backend dependencies, each fixable only by a major-version bump** — deliberately not force-upgraded as part of this hardening phase; CI runs `dependency-scan`/Trivy report-only (`continue-on-error`) rather than blocking on them until each is upgraded and regression-tested as its own change:
  - `cryptography` 43.0.3 → 48.0.1/49.0.0 (used for connector-token encryption, `core/security.py`'s transitive deps)
  - `pypdf` 4.3.1 → 6.x (PDF text extraction, `ingestion`)
  - `pytest` 8.4.2 → 9.0.3 (dev/test-only — not present in the production image, so no runtime exposure)
  - `starlette` 0.46.2 → 0.47.2/0.49.1/1.x (FastAPI's transport layer — a major bump here needs care around the SSE streaming behavior `assistant/router.py` and `core/middleware.py` depend on)
  - `transformers` 4.57.6 → 5.x (local embedding model, `ai`/`ingestion`)

  Track each as its own upgrade PR (Dependabot will also propose these); re-run `pip-audit --skip-editable` after each to confirm it clears, and flip `dependency-scan`/Trivy back to blocking once the backlog is empty.
- **Webhook signing has no replay window** (documented in Phase 18's shipping notes) — the signature proves authenticity, not freshness. Acceptable for v1; a `X-Helix-Timestamp` + tolerance window is a candidate for a later phase if a receiver needs replay protection.
- **`ruff`'s `flake8-bandit` (`S`) rule set is not enabled.** It would surface a large, unscoped backlog across every existing module rather than "closing a gap" — deliberately deferred to a dedicated cleanup pass rather than folded into this phase.
- **No frontend CSP/XSS-specific audit** beyond the "encode all output" rule (CLAUDE.md §8) and Next.js's own defaults — the backend's `Content-Security-Policy: default-src 'none'` only governs API responses, which are JSON-only and never rendered as HTML. A dedicated frontend security pass is a candidate for a future phase if needed.
- **HTTP method/replay abuse of idempotent-looking endpoints** (e.g. repeated `POST /auth/register`) is bounded by validation (duplicate email rejected) but not separately rate-limited beyond login; revisit if abuse is observed.
