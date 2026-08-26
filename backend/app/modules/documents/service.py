import logging
import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.storage import upload_object
from app.core.tenancy import set_tenant_context
from app.modules.auth.models import User
from app.modules.documents.models import Document, DocumentACL, Source
from app.modules.ingestion import service as ingestion_service
from app.modules.ingestion.models import Job

logger = logging.getLogger("helix.documents")


async def get_or_create_manual_source(db: AsyncSession, org_id: uuid.UUID) -> Source:
    result = await db.execute(
        select(Source).where(Source.org_id == org_id, Source.type == "manual")
    )
    source = result.scalar_one_or_none()
    if source is not None:
        return source

    source = Source(org_id=org_id, type="manual", name="Manual uploads")
    db.add(source)
    await db.flush()
    return source


async def upload_document(
    db: AsyncSession, org_id: uuid.UUID, uploader: User, file: UploadFile
) -> Document:
    source = await get_or_create_manual_source(db, org_id)

    document_id = uuid.uuid4()
    storage_key = f"{org_id}/{document_id}/{file.filename}"
    # PayloadTooLargeError (from core.storage) propagates straight out of
    # this call if the file exceeds the configured limit — nothing is
    # committed to the DB in that case.
    checksum = await upload_object(file.file, storage_key)

    document = Document(
        id=document_id,
        org_id=org_id,
        source_id=source.id,
        title=file.filename or "untitled",
        mime=file.content_type or "application/octet-stream",
        storage_key=storage_key,
        checksum=checksum,
        uploaded_by_user_id=uploader.id,
    )
    db.add(document)
    await db.flush()

    # Default ACL: visible to the whole org. Finer-grained principals
    # ("user", "role") land once connectors (Phase 14) or per-user sharing
    # need to express narrower visibility than this.
    db.add(
        DocumentACL(
            org_id=org_id, document_id=document.id, principal_type="org", principal_id=org_id
        )
    )

    await db.commit()
    # db.commit() ends the transaction, and with it the SET LOCAL/set_config
    # tenant context RLS needs (see Phase 5's identical lesson) — Document is
    # RLS-protected, so refresh() would otherwise come back empty.
    await set_tenant_context(db, org_id)
    await db.refresh(document)
    logger.info("document uploaded: %s in org %s by %s", document.id, org_id, uploader.id)

    await ingestion_service.trigger_ingestion(db, org_id, document.id)
    return document


async def list_documents(db: AsyncSession, org_id: uuid.UUID) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.org_id == org_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def get_document(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    # Defensive, not redundant: callers elsewhere in the pipeline (e.g.
    # ingest_document_task) call this right after a db.commit() on the same
    # session, which wipes the SET LOCAL/set_config tenant context RLS
    # needs (Phase 5/6/7's recurring lesson). Re-setting here means every
    # caller of get_document is safe by construction, not by remembering to.
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id, Document.deleted_at.is_(None)
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise NotFoundError("document not found")
    return document


async def delete_document(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """Soft delete only — the object stays in MinIO. Physical cleanup is a
    background-job concern, not in scope for this phase."""
    document = await get_document(db, org_id, document_id)
    document.deleted_at = datetime.now(UTC)
    await db.commit()
    logger.info("document deleted: %s in org %s", document_id, org_id)


async def reindex_document(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> Job:
    await get_document(db, org_id, document_id)  # 404s if missing/not this org
    return await ingestion_service.trigger_ingestion(db, org_id, document_id)


async def mark_document_status(
    db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID, status: str
) -> None:
    """Public entry point for other modules (ingestion) to update a
    document's status without importing/querying the Document model
    directly (CLAUDE.md §3)."""
    document = await get_document(db, org_id, document_id)
    document.status = status
    await db.commit()


async def get_document_acl_principals(
    db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID
) -> list[tuple[str, uuid.UUID]]:
    # Same defensive reasoning as get_document — DocumentACL is RLS-protected
    # too, and this can be called after another commit reset the context.
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(DocumentACL.principal_type, DocumentACL.principal_id).where(
            DocumentACL.org_id == org_id, DocumentACL.document_id == document_id
        )
    )
    return [(principal_type, principal_id) for principal_type, principal_id in result.all()]


async def get_document_storage_info(
    db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[str, str]:
    """Returns (storage_key, mime) — the minimum ingestion needs to fetch
    and interpret the file, without handing over the full Document row."""
    document = await get_document(db, org_id, document_id)
    return document.storage_key, document.mime
