import hashlib
import logging
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.storage import download_object
from app.core.tenancy import set_tenant_context
from app.modules.documents import service as documents_service
from app.modules.ingestion.chunking import chunk_text
from app.modules.ingestion.embeddings import embed_texts
from app.modules.ingestion.extraction import extract_text
from app.modules.ingestion.models import Chunk

logger = logging.getLogger("helix.ingestion")


def _compute_acl_hash(principals: list[tuple[str, uuid.UUID]]) -> str:
    normalized = sorted(f"{ptype}:{pid}" for ptype, pid in principals)
    return hashlib.sha256("|".join(normalized).encode()).hexdigest()


async def run_ingestion(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> int:
    """Extract -> chunk -> embed -> upsert for one document. Returns the
    chunk count written. Safe to re-run (reindex): replaces the document's
    existing chunks rather than appending to them.
    """
    settings = get_settings()

    # Every downstream call touches RLS-protected tables (documents,
    # document_acls, chunks) — must be set before any of them.
    await set_tenant_context(db, org_id)

    storage_key, mime = await documents_service.get_document_storage_info(db, org_id, document_id)
    content = await download_object(storage_key)
    text = extract_text(content, mime)

    pieces = chunk_text(
        text, settings.ingestion_chunk_tokens, settings.ingestion_chunk_overlap_tokens
    )
    embeddings = embed_texts(pieces)

    principals = await documents_service.get_document_acl_principals(db, org_id, document_id)
    acl_hash = _compute_acl_hash(principals)

    await db.execute(delete(Chunk).where(Chunk.document_id == document_id, Chunk.org_id == org_id))
    for ordinal, (piece, embedding) in enumerate(zip(pieces, embeddings, strict=True)):
        db.add(
            Chunk(
                org_id=org_id,
                document_id=document_id,
                ordinal=ordinal,
                content=piece,
                embedding=embedding,
                acl_hash=acl_hash,
            )
        )

    await db.commit()
    return len(pieces)
