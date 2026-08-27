"""Eval harness (SPEC.md §17/§41 Phase 11). Two independent scores:

- Retrieval (hit-rate/MRR): pure `search_service` calls, no LLM involved —
  free, deterministic, always safe to run in CI.
- Answer quality (grounded rate): actually generates an answer via
  `assistant_service.query`, so it makes a real LLM call per case unless the
  caller has mocked `ai_service.stream_completion`. Grounding is scored with
  a heuristic (the answer cites the expected document AND mentions an
  expected keyword) rather than an LLM-as-judge, to avoid a second paid call
  per case just to score the first one.

Callers decide whether "real LLM call" is acceptable — this module has no
opinion on cost gating (see backend/app/tests/test_ai_evals.py for the
RUN_LIVE_EVALS opt-in gate that keeps CI free by default).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.evals.dataset import CASES
from app.modules.assistant import service as assistant_service
from app.modules.search import service as search_service

# Regression thresholds. A dataset change (dataset.py) can shift what these
# numbers mean — review them together.
MIN_HIT_RATE = 0.8
MIN_MRR = 0.6
MIN_GROUNDED_RATE = 0.7

_RETRIEVAL_TOP_K = 5


@dataclass(frozen=True)
class RetrievalEvalReport:
    hit_rate: float
    mrr: float
    n_cases: int


@dataclass(frozen=True)
class AnswerQualityReport:
    grounded_rate: float
    n_cases: int


async def run_retrieval_eval(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    doc_ids_by_key: dict[str, uuid.UUID],
) -> RetrievalEvalReport:
    hits = 0
    reciprocal_ranks: list[float] = []
    for case in CASES:
        expected_id = doc_ids_by_key[case.expected_doc_key]
        results, _ = await search_service.search(
            db, org_id, user_id, case.query, limit=_RETRIEVAL_TOP_K, cursor=None
        )
        rank = next(
            (i for i, result in enumerate(results, start=1) if result.document_id == expected_id),
            None,
        )
        if rank is not None:
            hits += 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)

    n = len(CASES)
    return RetrievalEvalReport(hit_rate=hits / n, mrr=sum(reciprocal_ranks) / n, n_cases=n)


async def run_answer_quality_eval(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    doc_ids_by_key: dict[str, uuid.UUID],
) -> AnswerQualityReport:
    grounded = 0
    for case in CASES:
        conversation = await assistant_service.resolve_conversation(
            db, org_id, user_id, None, case.query
        )
        events = [
            event
            async for event in assistant_service.query(
                db, org_id, user_id, conversation.id, case.query
            )
        ]
        answer_text = "".join(
            event.text for event in events if isinstance(event, assistant_service.AnswerToken)
        )
        done = next(event for event in events if isinstance(event, assistant_service.AnswerDone))

        expected_id = doc_ids_by_key[case.expected_doc_key]
        cites_expected_doc = any(citation.document_id == expected_id for citation in done.citations)
        mentions_keyword = any(
            keyword.lower() in answer_text.lower() for keyword in case.expected_keywords
        )
        if cites_expected_doc and mentions_keyword:
            grounded += 1

    n = len(CASES)
    return AnswerQualityReport(grounded_rate=grounded / n, n_cases=n)
