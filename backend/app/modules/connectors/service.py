import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.queue import enqueue_connector_sync
from app.modules.connectors import github as github_connector
from app.modules.connectors.crypto import decrypt_token, encrypt_token
from app.modules.connectors.registry import CONNECTORS
from app.modules.connectors.web import validate_urls
from app.modules.documents import service as documents_service
from app.modules.documents.models import Source
from app.modules.notifications import service as notifications_service

logger = logging.getLogger("helix.connectors")

# The OAuth `state` param carries its payload encrypted (reusing
# crypto.py's Fernet, not a separate mechanism) rather than a random
# opaque token needing server-side pending-state storage -- the callback
# is a stateless GET from GitHub, so everything it needs (org_id, the
# connecting user, which repo) must round-trip through `state` itself.
_STATE_TTL_SECONDS = 600


def _decrypt_config(config: dict[str, Any]) -> dict[str, Any]:
    oauth = config.get("oauth")
    if not oauth:
        return config
    decrypted_oauth = dict(oauth)
    if oauth.get("access_token"):
        decrypted_oauth["access_token"] = decrypt_token(oauth["access_token"])
    if oauth.get("refresh_token"):
        decrypted_oauth["refresh_token"] = decrypt_token(oauth["refresh_token"])
    return {**config, "oauth": decrypted_oauth}


def _encrypt_config(config: dict[str, Any]) -> dict[str, Any]:
    oauth = config.get("oauth")
    if not oauth:
        return config
    encrypted_oauth = dict(oauth)
    if oauth.get("access_token"):
        encrypted_oauth["access_token"] = encrypt_token(oauth["access_token"])
    if oauth.get("refresh_token"):
        encrypted_oauth["refresh_token"] = encrypt_token(oauth["refresh_token"])
    return {**config, "oauth": encrypted_oauth}


async def create_web_connector(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, name: str, url_list: list[str]
) -> Source:
    validate_urls(url_list)  # fail fast on a disallowed host, not silently at sync time
    config = {"url_list": url_list, "connected_by_user_id": str(user_id), "cursor": None}
    source = await documents_service.create_source(db, org_id, "web", name, config)
    logger.info("web connector created: %s in org %s", source.id, org_id)
    return source


def start_github_oauth(org_id: uuid.UUID, user_id: uuid.UUID, repo: str, branch: str) -> str:
    state = encrypt_token(
        json.dumps({"org_id": str(org_id), "user_id": str(user_id), "repo": repo, "branch": branch})
    )
    return github_connector.build_authorize_url(_redirect_uri(), state)


async def complete_github_oauth(db: AsyncSession, code: str, state: str) -> Source:
    try:
        payload = json.loads(decrypt_token(state, ttl_seconds=_STATE_TTL_SECONDS))
    except (InvalidToken, ValueError) as exc:
        raise UnauthorizedError("invalid or expired OAuth state") from exc

    org_id = uuid.UUID(payload["org_id"])
    user_id = uuid.UUID(payload["user_id"])
    token_response = await github_connector.exchange_code_for_token(code, _redirect_uri())

    config = {
        "repo": payload["repo"],
        "branch": payload["branch"],
        "connected_by_user_id": str(user_id),
        "cursor": None,
        "oauth": {
            "access_token": encrypt_token(token_response["access_token"]),
            "refresh_token": (
                encrypt_token(token_response["refresh_token"])
                if token_response.get("refresh_token")
                else None
            ),
            "expires_at": None,
        },
    }
    source = await documents_service.create_source(db, org_id, "github", payload["repo"], config)
    logger.info("github connector connected: %s (%s) in org %s", source.id, payload["repo"], org_id)
    return source


def _redirect_uri() -> str:
    return get_settings().github_oauth_redirect_url


async def list_connectors(db: AsyncSession, org_id: uuid.UUID) -> list[Source]:
    return await documents_service.list_connector_sources(db, org_id)


async def get_connector(db: AsyncSession, org_id: uuid.UUID, source_id: uuid.UUID) -> Source:
    return await documents_service.get_source(db, org_id, source_id)


async def trigger_sync(db: AsyncSession, org_id: uuid.UUID, source_id: uuid.UUID) -> Source:
    source = await documents_service.get_source(
        db, org_id, source_id
    )  # 404s if missing/not this org
    await enqueue_connector_sync(source.id, org_id)
    return source


async def disconnect_connector(db: AsyncSession, org_id: uuid.UUID, source_id: uuid.UUID) -> None:
    await documents_service.delete_source(db, org_id, source_id)
    logger.info("connector disconnected: %s in org %s", source_id, org_id)


async def run_sync(db: AsyncSession, org_id: uuid.UUID, source_id: uuid.UUID) -> None:
    """The connector-agnostic sync loop -- drives whichever Connector
    Source.type resolves to identically. Called from
    connectors/tasks.py::sync_connector_task.
    """
    source = await documents_service.get_source(db, org_id, source_id)
    connector = CONNECTORS[source.type]
    connected_by_user_id = uuid.UUID(source.config["connected_by_user_id"])

    await documents_service.update_source(db, org_id, source_id, status="syncing")

    try:
        config = await connector.authenticate(_decrypt_config(source.config))
        cursor = config.get("cursor")
        items, new_cursor = await connector.list_changes(config, cursor)

        existing_documents = await documents_service.list_documents_by_source(db, org_id, source_id)
        existing_by_external_id = {
            document.external_id: document
            for document in existing_documents
            if document.external_id is not None
        }
        seen_external_ids: set[str] = set()

        for item in items:
            seen_external_ids.add(item.external_id)
            fetched = await connector.fetch(config, item)
            new_checksum = hashlib.sha256(fetched.content).hexdigest()
            existing = existing_by_external_id.get(item.external_id)

            if existing is None:
                acl_principals = await connector.map_acls(config, org_id, item)
                await documents_service.create_document_from_source(
                    db,
                    org_id,
                    source_id,
                    item.external_id,
                    fetched.title,
                    fetched.mime,
                    fetched.content,
                    connected_by_user_id,
                    acl_principals,
                )
            elif existing.checksum != new_checksum:
                await documents_service.update_document_content(
                    db, org_id, existing.id, fetched.title, fetched.mime, fetched.content
                )
            # else: checksum unchanged -- zero writes, this is the sync's idempotency guarantee

        # Anything previously synced from this source but absent from this
        # sync's listing was deleted upstream -- soft-delete to match.
        for external_id, document in existing_by_external_id.items():
            if external_id not in seen_external_ids:
                await documents_service.delete_document(db, org_id, document.id)

        config["cursor"] = new_cursor
        await documents_service.update_source(
            db,
            org_id,
            source_id,
            config=_encrypt_config(config),
            status="active",
            last_synced_at=datetime.now(UTC),
            last_sync_error=None,
        )
        logger.info(
            "connector sync finished: source=%s items=%s deleted=%s",
            source_id,
            len(items),
            len(existing_by_external_id) - len(seen_external_ids & existing_by_external_id.keys()),
        )
    except Exception as exc:
        logger.exception("connector sync failed: source=%s", source_id)
        await documents_service.update_source(
            db, org_id, source_id, status="error", last_sync_error=str(exc)
        )
        # The one real system-notification producer this phase wires up
        # (Phase 15) -- notify whoever connected the source, since a
        # failed sync otherwise has zero user-facing signal beyond a DB
        # column nobody's watching.
        await notifications_service.notify(
            db,
            org_id,
            connected_by_user_id,
            event_type="connector.sync_failed",
            payload={"source_name": source.name, "error": str(exc)},
        )
        raise
