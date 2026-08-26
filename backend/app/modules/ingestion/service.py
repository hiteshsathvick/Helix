import hashlib
import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue import enqueue_ingestion_job
from app.core.tenancy import set_tenant_context
from app.modules.ingestion.models import Chunk, Job

logger = logging.getLogger("helix.ingestion")


def compute_acl_hash(principals: list[tuple[str, uuid.UUID]]) -> str:
    """Public so other modules (search) can hash a *candidate* principal
    set — e.g. "what would this user's own ACL look like" — and compare
    against `Chunk.acl_hash` without needing their own copy of this logic.
    """
    normalized = sorted(f"{ptype}:{pid}" for ptype, pid in principals)
    return hashlib.sha256("|".join(normalized).encode()).hexdigest()


async def trigger_ingestion(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> Job:
    job = Job(org_id=org_id, document_id=document_id, kind="ingest_document", status="pending")
    db.add(job)
    await db.commit()
    # db.commit() wipes the SET LOCAL/set_config tenant context RLS needs
    # (Phase 5/6 lesson) — Job is RLS-protected, so refresh() needs it reset.
    await set_tenant_context(db, org_id)
    await db.refresh(job)

    await enqueue_ingestion_job(job.id, org_id, document_id)
    logger.info("ingestion job enqueued: %s for document %s", job.id, document_id)
    return job


async def get_latest_job(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> Job | None:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Job)
        .where(Job.org_id == org_id, Job.document_id == document_id)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# --- Chunk read primitives for other modules (search). `chunks` is this
# module's table (Phase 7 owns the schema/indexes); search never queries it
# directly (CLAUDE.md §3) — it only calls these. ---


async def lexical_search_chunks(
    db: AsyncSession,
    org_id: uuid.UUID,
    acl_hashes: list[str],
    query_text: str,
    limit: int,
) -> Sequence[Row]:
    await set_tenant_context(db, org_id)
    tsquery = func.plainto_tsquery("english", query_text)
    rank = func.ts_rank(Chunk.tsv, tsquery).label("rank")
    stmt = (
        select(Chunk.id, Chunk.document_id, Chunk.ordinal, rank)
        .where(
            Chunk.org_id == org_id,
            Chunk.acl_hash.in_(acl_hashes),
            Chunk.tsv.op("@@")(tsquery),
        )
        .order_by(rank.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.all()


async def semantic_search_chunks(
    db: AsyncSession,
    org_id: uuid.UUID,
    acl_hashes: list[str],
    query_embedding: list[float],
    limit: int,
) -> Sequence[Row]:
    await set_tenant_context(db, org_id)
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
    stmt = (
        select(Chunk.id, Chunk.document_id, Chunk.ordinal, distance)
        .where(
            Chunk.org_id == org_id,
            Chunk.acl_hash.in_(acl_hashes),
            Chunk.embedding.isnot(None),
        )
        .order_by(distance.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.all()


async def get_snippets(
    db: AsyncSession,
    org_id: uuid.UUID,
    chunk_ids: list[uuid.UUID],
    query_text: str,
    start_sel: str,
    stop_sel: str,
) -> dict[uuid.UUID, str]:
    """`start_sel`/`stop_sel` mark matched terms in the returned snippet.
    Callers choose these — chunk content is untrusted (CLAUDE.md §5), so a
    caller rendering to HTML must pick markers a frontend can split on
    safely, never Postgres's own `<b>...</b>` default, which would make
    rendering the result require trusting document content as HTML.
    """
    await set_tenant_context(db, org_id)
    tsquery = func.plainto_tsquery("english", query_text)
    options = f"StartSel={start_sel}, StopSel={stop_sel}"
    headline = func.ts_headline("english", Chunk.content, tsquery, options).label("snippet")
    stmt = select(Chunk.id, headline).where(Chunk.org_id == org_id, Chunk.id.in_(chunk_ids))
    result = await db.execute(stmt)
    return {row.id: row.snippet for row in result.all()}
