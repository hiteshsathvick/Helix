import io
import logging
import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.storage import upload_object
from app.core.tenancy import set_tenant_context
from app.modules.auth.models import User
from app.modules.documents.models import Document, DocumentACL, Source
from app.modules.ingestion import service as ingestion_service
from app.modules.ingestion.models import Job

logger = logging.getLogger("helix.documents")


def _manual_source_query(org_id: uuid.UUID):
    return select(Source).where(
        Source.org_id == org_id, Source.type == "manual", Source.deleted_at.is_(None)
    )


async def get_or_create_manual_source(db: AsyncSession, org_id: uuid.UUID) -> Source:
    result = await db.execute(_manual_source_query(org_id))
    source = result.scalar_one_or_none()
    if source is not None:
        return source

    source = Source(org_id=org_id, type="manual", name="Manual uploads")
    db.add(source)
    try:
        await db.flush()
    except IntegrityError:
        # Lost the race to a concurrent first-upload for this org --
        # ix_sources_org_id_manual_singleton (Phase 20 migration
        # 11400a085f70) means the loser always gets exactly this error,
        # never a duplicate row. A SAVEPOINT (db.begin_nested()) looks
        # like the more surgical fix here, but doesn't actually leave the
        # session usable afterward under this SQLAlchemy/asyncpg stack --
        # confirmed empirically (PendingRollbackError on the very next
        # statement) before falling back to this plain rollback, which
        # does. Callers must treat every *other* object already loaded in
        # this session as expired after this call returns (see
        # upload_document, which captures uploader.id before calling this
        # rather than reading it afterward) -- rollback() expires the
        # whole session's identity map, not just this insert.
        await db.rollback()
        # set_tenant_context uses set_config(..., is_local=true) -- a
        # transaction-scoped SET LOCAL, wiped by the rollback above like
        # everything else in that transaction. Without re-setting it here,
        # RLS hides even the winner's own now-committed row from the
        # re-query below (same class of bug as the create-then-refresh
        # pattern documented on the agents module).
        await set_tenant_context(db, org_id)
        result = await db.execute(_manual_source_query(org_id))
        source = result.scalar_one()
    return source


async def create_source(
    db: AsyncSession, org_id: uuid.UUID, source_type: str, name: str, config: dict
) -> Source:
    """Generic Source creation for connectors (Phase 14) — `source_type` is
    e.g. "web"/"github", never "manual" (that's get_or_create_manual_source's
    job). Source is this module's model; connectors calls this rather than
    constructing a Source itself (CLAUDE.md §3)."""
    await set_tenant_context(db, org_id)
    source = Source(org_id=org_id, type=source_type, name=name, config=config)
    db.add(source)
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(source)
    return source


async def list_connector_sources(db: AsyncSession, org_id: uuid.UUID) -> list[Source]:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Source).where(
            Source.org_id == org_id, Source.type != "manual", Source.deleted_at.is_(None)
        )
    )
    return list(result.scalars().all())


async def get_source(db: AsyncSession, org_id: uuid.UUID, source_id: uuid.UUID) -> Source:
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Source).where(
            Source.id == source_id, Source.org_id == org_id, Source.deleted_at.is_(None)
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise NotFoundError("connector not found")
    return source


async def update_source(
    db: AsyncSession,
    org_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    config: dict | None = None,
    status: str | None = None,
    last_synced_at: datetime | None = None,
    last_sync_error: str | None = "__unset__",
) -> Source:
    """last_sync_error's default is a sentinel, not None, so callers can
    explicitly clear it (pass None) on a successful sync without every
    other caller needing to repeat that -- omitting the kwarg leaves it
    untouched."""
    source = await get_source(db, org_id, source_id)
    if config is not None:
        source.config = config
    if status is not None:
        source.status = status
    if last_synced_at is not None:
        source.last_synced_at = last_synced_at
    if last_sync_error != "__unset__":
        source.last_sync_error = last_sync_error
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(source)
    return source


async def delete_source(db: AsyncSession, org_id: uuid.UUID, source_id: uuid.UUID) -> None:
    """Soft delete only -- previously-synced documents stay searchable,
    matching delete_document's own reasoning."""
    source = await get_source(db, org_id, source_id)
    source.deleted_at = datetime.now(UTC)
    await db.commit()


async def upload_document(
    db: AsyncSession, org_id: uuid.UUID, uploader: User, file: UploadFile
) -> Document:
    # Captured before get_or_create_manual_source, not read off `uploader`
    # afterward: a lost race there rolls back this session (Phase 20),
    # which expires every already-loaded object in it -- including
    # `uploader`, loaded earlier by the get_current_user dependency in
    # this same session. Accessing uploader.id post-rollback would trigger
    # an implicit re-fetch that can itself fail under the same concurrent
    # load; a plain UUID captured now has no such lifecycle to worry about.
    uploader_id = uploader.id
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
        uploaded_by_user_id=uploader_id,
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
    logger.info("document uploaded: %s in org %s by %s", document.id, org_id, uploader_id)

    await ingestion_service.trigger_ingestion(db, org_id, document.id)
    return document


async def create_document_from_source(
    db: AsyncSession,
    org_id: uuid.UUID,
    source_id: uuid.UUID,
    external_id: str,
    title: str,
    mime: str,
    content: bytes,
    connected_by_user_id: uuid.UUID,
    acl_principals: list[tuple[str, uuid.UUID]] | None = None,
) -> Document:
    """The connector-sync equivalent of upload_document: content already
    fetched (not an UploadFile), a specific source_id/external_id rather
    than the manual source, and caller-supplied ACL principals rather than
    an always-org-wide default. Used by app/modules/connectors/service.py's
    sync loop for a newly-discovered item; see update_document_content for
    an existing item whose content changed.
    """
    await set_tenant_context(db, org_id)
    document_id = uuid.uuid4()
    # Unlike upload_document's filename-derived key, `title` here can be
    # anything a connector produced -- a full URL for the web connector,
    # a repo path for GitHub -- and isn't safe to embed directly in an S3
    # object key (MinIO rejects e.g. "://" in a key).
    storage_key = f"{org_id}/{document_id}"
    checksum = await upload_object(io.BytesIO(content), storage_key)

    document = Document(
        id=document_id,
        org_id=org_id,
        source_id=source_id,
        external_id=external_id,
        title=title,
        mime=mime,
        storage_key=storage_key,
        checksum=checksum,
        uploaded_by_user_id=connected_by_user_id,
    )
    db.add(document)
    await db.flush()

    for principal_type, principal_id in acl_principals or [("org", org_id)]:
        db.add(
            DocumentACL(
                org_id=org_id,
                document_id=document.id,
                principal_type=principal_type,
                principal_id=principal_id,
            )
        )

    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(document)
    logger.info(
        "document created from source: %s (source=%s external_id=%r)",
        document.id,
        source_id,
        external_id,
    )

    await ingestion_service.trigger_ingestion(db, org_id, document.id)
    return document


async def update_document_content(
    db: AsyncSession,
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    title: str,
    mime: str,
    content: bytes,
) -> Document:
    """A connector-sync found the same external_id with different content --
    re-upload, update the pointer/checksum/title, and re-trigger ingestion
    (which replaces the document's existing chunks, see
    ingestion/pipeline.py::run_ingestion's docstring)."""
    document = await get_document(db, org_id, document_id)
    storage_key = f"{org_id}/{document_id}"  # see create_document_from_source's identical note
    checksum = await upload_object(io.BytesIO(content), storage_key)

    document.title = title
    document.mime = mime
    document.storage_key = storage_key
    document.checksum = checksum
    await db.commit()
    await set_tenant_context(db, org_id)
    await db.refresh(document)

    await ingestion_service.trigger_ingestion(db, org_id, document.id)
    return document


async def get_status_counts(db: AsyncSession, org_id: uuid.UUID) -> dict[str, int]:
    """Ingestion health (SPEC.md §27) -- current state, not a monthly
    window: a stuck "error" document from three months ago is still
    unhealthy today. analytics/service.py calls this rather than querying
    `documents` directly (CLAUDE.md §3)."""
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Document.status, func.count())
        .where(Document.org_id == org_id, Document.deleted_at.is_(None))
        .group_by(Document.status)
    )
    return {status: count for status, count in result.all()}


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


async def get_document_by_external_id(
    db: AsyncSession, org_id: uuid.UUID, source_id: uuid.UUID, external_id: str
) -> Document | None:
    """The dedup lookup a connector sync (Phase 14) uses to decide
    create-vs-update-vs-skip for one ChangeItem — see
    app/modules/connectors/service.py's sync loop."""
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Document).where(
            Document.org_id == org_id,
            Document.source_id == source_id,
            Document.external_id == external_id,
            Document.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_documents_by_source(
    db: AsyncSession, org_id: uuid.UUID, source_id: uuid.UUID
) -> list[Document]:
    """Every non-deleted document a connector has previously synced for one
    source -- a sync compares this set's external_ids against the current
    upstream listing to detect items deleted upstream (see
    connectors/service.py)."""
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Document).where(
            Document.org_id == org_id,
            Document.source_id == source_id,
            Document.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


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


async def get_document_titles(
    db: AsyncSession, org_id: uuid.UUID, document_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """For search (Phase 8): titles for citations, doubling as an existence
    check — a soft-deleted or missing document simply won't be a key in the
    returned dict, letting callers drop chunks that belong to it."""
    if not document_ids:
        return {}
    await set_tenant_context(db, org_id)
    result = await db.execute(
        select(Document.id, Document.title).where(
            Document.org_id == org_id,
            Document.id.in_(document_ids),
            Document.deleted_at.is_(None),
        )
    )
    return {document_id: title for document_id, title in result.all()}
