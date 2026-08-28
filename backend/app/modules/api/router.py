import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.modules.api import service
from app.modules.api.dependencies import ApiKeyPrincipal, require_api_key
from app.modules.api.schemas import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyRead,
    WebhookCreate,
    WebhookCreatedResponse,
    WebhookDeliveryRead,
    WebhookRead,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.documents import service as documents_service
from app.modules.documents.schemas import DocumentRead
from app.modules.orgs.dependencies import require_permission
from app.modules.orgs.system_roles import PERMISSION_API_KEYS_MANAGE, PERMISSION_WEBHOOKS_MANAGE
from app.modules.search import service as search_service
from app.modules.search.schemas import SearchResponse

# --- dashboard-managed: API keys ---

router = APIRouter(prefix="/orgs/{org_id}/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_API_KEYS_MANAGE)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreatedResponse:
    key, raw_key = await service.create_api_key(db, org_id, current_user, body.name, body.scopes)
    return ApiKeyCreatedResponse(key=ApiKeyRead.model_validate(key), raw_key=raw_key)


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_API_KEYS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyRead]:
    keys = await service.list_api_keys(db, org_id)
    return [ApiKeyRead.model_validate(k) for k in keys]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_API_KEYS_MANAGE)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.revoke_api_key(db, org_id, key_id, current_user.id)


# --- dashboard-managed: webhooks ---

webhooks_router = APIRouter(prefix="/orgs/{org_id}/webhooks", tags=["webhooks"])


@webhooks_router.post(
    "", response_model=WebhookCreatedResponse, status_code=status.HTTP_201_CREATED
)
async def create_webhook(
    body: WebhookCreate,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WEBHOOKS_MANAGE)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookCreatedResponse:
    webhook, secret = await service.create_webhook(db, org_id, current_user, body.url, body.events)
    return WebhookCreatedResponse(webhook=WebhookRead.model_validate(webhook), secret=secret)


@webhooks_router.get("", response_model=list[WebhookRead])
async def list_webhooks(
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WEBHOOKS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookRead]:
    webhooks = await service.list_webhooks(db, org_id)
    return [WebhookRead.model_validate(w) for w in webhooks]


@webhooks_router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_webhook(
    webhook_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WEBHOOKS_MANAGE)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.deactivate_webhook(db, org_id, webhook_id, current_user.id)


@webhooks_router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryRead])
async def list_deliveries(
    webhook_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_permission(PERMISSION_WEBHOOKS_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookDeliveryRead]:
    deliveries = await service.list_deliveries(db, org_id, webhook_id)
    return [WebhookDeliveryRead.model_validate(d) for d in deliveries]


# --- public API subset (SPEC.md §18) -- key-scoped, not session-based ---

public_router = APIRouter(prefix="/public", tags=["public-api"])


@public_router.get("/search", response_model=SearchResponse)
async def public_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = Query(None),
    principal: ApiKeyPrincipal = Depends(require_api_key("search:read")),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    results, next_cursor = await search_service.search(
        db, principal.org_id, principal.user_id, q, limit, cursor
    )
    return SearchResponse(results=results, next_cursor=next_cursor)


@public_router.get("/documents", response_model=list[DocumentRead])
async def public_list_documents(
    principal: ApiKeyPrincipal = Depends(require_api_key("documents:read")),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    documents = await documents_service.list_documents(db, principal.org_id)
    return [DocumentRead.model_validate(d) for d in documents]


@public_router.post("/documents", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def public_upload_document(
    file: UploadFile = File(...),
    principal: ApiKeyPrincipal = Depends(require_api_key("documents:write")),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    uploader = await db.get(User, principal.user_id)
    assert uploader is not None  # the key's creator always still exists as a user row
    document = await documents_service.upload_document(db, principal.org_id, uploader, file)
    return DocumentRead.model_validate(document)
