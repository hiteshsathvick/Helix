import base64
import logging
import uuid
from collections.abc import Sequence
from typing import Any, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.tenancy import set_tenant_context
from app.modules.documents import service as documents_service
from app.modules.ingestion import service as ingestion_service
from app.modules.ingestion.embeddings import embed_texts
from app.modules.search.schemas import SearchResult

logger = logging.getLogger("helix.search")

# Standard constant from the original RRF paper (Cormack et al., 2009) —
# large enough that a mediocre rank in one list doesn't get crushed by a
# great rank in the other.
_RRF_K = 60
# Each candidate list is over-fetched relative to the page being built, so
# that after fusion — and after dropping chunks whose document turns out to
# be soft-deleted — there's still enough left to fill a full page.
_CANDIDATE_MULTIPLIER = 4

# Snippet highlight markers. Control characters, not HTML tags: chunk
# content is untrusted (CLAUDE.md §5), so the API contract is "plain text
# with these two characters as highlight boundaries" — a frontend renders
# them by splitting the string, never by treating the snippet as HTML.
HIGHLIGHT_START = "\x01"
HIGHLIGHT_STOP = "\x02"


class _FusedHit(NamedTuple):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    ordinal: int
    score: float


def _visible_acl_hashes(org_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    """The hashes `Chunk.acl_hash` would take for every principal set this
    user is currently known to belong to. Every document today only ever
    gets a single-principal ACL row (Phase 6/7: "org"-wide on upload), so
    hashing the user's own single-principal identities is sufficient; a
    document ACL'd to *multiple* principals at once (Phase 14) would need a
    real document_acls join instead of this hash-matching shortcut.
    """
    return [
        ingestion_service.compute_acl_hash([("org", org_id)]),
        ingestion_service.compute_acl_hash([("user", user_id)]),
    ]


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("invalid cursor") from exc
    if offset < 0:
        raise ValidationError("invalid cursor")
    return offset


def _reciprocal_rank_fusion(
    lexical_hits: Sequence[Any], semantic_hits: Sequence[Any]
) -> list[_FusedHit]:
    # Sequence[Any], not a precise Row protocol: both real SQLAlchemy Row
    # objects (from ingestion_service) and the plain duck-typed test double
    # in test_search.py only need `.id`/`.document_id`/`.ordinal` via
    # attribute access, which isn't something Row exposes statically.
    scores: dict[uuid.UUID, float] = {}
    meta: dict[uuid.UUID, tuple[uuid.UUID, int]] = {}

    for hits in (lexical_hits, semantic_hits):
        for rank, hit in enumerate(hits, start=1):
            scores[hit.id] = scores.get(hit.id, 0.0) + 1 / (_RRF_K + rank)
            meta[hit.id] = (hit.document_id, hit.ordinal)

    fused = [
        _FusedHit(
            chunk_id=chunk_id, document_id=meta[chunk_id][0], ordinal=meta[chunk_id][1], score=score
        )
        for chunk_id, score in scores.items()
    ]
    fused.sort(key=lambda hit: hit.score, reverse=True)
    return fused


async def search(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    limit: int,
    cursor: str | None,
) -> tuple[list[SearchResult], str | None]:
    await set_tenant_context(db, org_id)
    offset = _decode_cursor(cursor)
    acl_hashes = _visible_acl_hashes(org_id, user_id)

    candidate_limit = (offset + limit) * _CANDIDATE_MULTIPLIER
    [query_embedding] = embed_texts([query])

    lexical_hits = await ingestion_service.lexical_search_chunks(
        db, org_id, acl_hashes, query, candidate_limit
    )
    semantic_hits = await ingestion_service.semantic_search_chunks(
        db, org_id, acl_hashes, query_embedding, candidate_limit
    )
    fused = _reciprocal_rank_fusion(lexical_hits, semantic_hits)

    document_ids = {hit.document_id for hit in fused}
    titles = await documents_service.get_document_titles(db, org_id, document_ids)
    visible = [hit for hit in fused if hit.document_id in titles]

    page = visible[offset : offset + limit]
    next_cursor = _encode_cursor(offset + limit) if len(visible) > offset + limit else None

    snippets = await ingestion_service.get_snippets(
        db, org_id, [hit.chunk_id for hit in page], query, HIGHLIGHT_START, HIGHLIGHT_STOP
    )

    results = [
        SearchResult(
            document_id=hit.document_id,
            document_title=titles[hit.document_id],
            chunk_id=hit.chunk_id,
            ordinal=hit.ordinal,
            snippet=snippets.get(hit.chunk_id, ""),
            score=hit.score,
        )
        for hit in page
    ]
    return results, next_cursor
