# ADR 0002: Eval harness cost gating

## Context

Phase 11 (SPEC.md §17, §41) adds an eval harness scoring two things against a fixed dataset (`backend/app/modules/ai/evals/`):

- **Retrieval** (hit-rate/MRR) — pure `search_service` calls, no LLM involved.
- **Answer quality** (grounded rate) — generates a real answer via `assistant_service.query` for each eval case, which means a real, billed LLM call per case.

The roadmap line says the harness "runs in CI on a fixed dataset; regression thresholds." Every other test in this suite (`test_assistant.py`) already avoids calling a real provider by mocking `ai_service.stream_completion`, specifically because CI must stay free and deterministic — an external API's cost, latency, and uptime shouldn't gate a PR.

## Decision

Split the harness into two independently-gated pieces:

- The retrieval eval always runs for real in CI — it's free and deterministic, so there's no reason to gate it.
- The answer-quality eval only runs when both `RUN_LIVE_EVALS=1` and a real `ANTHROPIC_API_KEY` are present (`backend/app/tests/test_ai_evals.py`). Neither is set in CI by default, so it's skipped there; a developer runs it locally, opt-in, when they want to check for a quality regression against the real provider (~$0.02–0.05 per run against the current 6-case dataset).

## Consequences

- CI cost stays at $0 by default; no `ANTHROPIC_API_KEY` secret needs to be added to GitHub Actions for this phase.
- The literal "runs in CI" wording in the roadmap is satisfied for the retrieval half only. If real answer-quality regression detection in CI is wanted later, the fix is to add the secret and drop the `RUN_LIVE_EVALS` gate for that one test — the harness itself doesn't need to change.
- Answer-quality scoring uses a heuristic (citation of the expected document + keyword presence in the answer) rather than an LLM-as-judge, so it doesn't need a second paid call per case just to grade the first one.
