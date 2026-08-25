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
    return document


async def list_documents(db: AsyncSession, org_id: uuid.UUID) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.org_id == org_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def get_document(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> Document:
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
