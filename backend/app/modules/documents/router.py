import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.documents import service
from app.modules.documents.schemas import DocumentRead
from app.modules.orgs.dependencies import require_permission
from app.modules.orgs.system_roles import PERMISSION_DOCUMENTS_READ, PERMISSION_DOCUMENTS_WRITE

router = APIRouter(prefix="/orgs/{org_id}/documents", tags=["documents"])


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_DOCUMENTS_WRITE)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    document = await service.upload_document(db, org_id, current_user, file)
    return DocumentRead.model_validate(document)


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_DOCUMENTS_READ)),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    documents = await service.list_documents(db, org_id)
    return [DocumentRead.model_validate(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_DOCUMENTS_READ)),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    document = await service.get_document(db, org_id, document_id)
    return DocumentRead.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_DOCUMENTS_WRITE)),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete_document(db, org_id, document_id)
