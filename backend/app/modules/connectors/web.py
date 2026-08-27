"""Generic web/URL connector -- no OAuth. An org admin configures a static
list of URLs (Source.config["url_list"]); every sync re-lists that same
set (there's no API to "list changes" for arbitrary URLs) and relies on
the sync loop's per-item checksum diff for idempotency. Default-deny host
allowlist (SPEC.md §29), same shape as agents/tools.py's http_request tool
but a deliberately separate setting -- see connectors/service.py's
create_web_connector for why.
"""

import logging
import uuid
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import ValidationError
from app.modules.connectors.base import ChangeItem, Connector, FetchedContent

logger = logging.getLogger("helix.connectors")


def _host_allowed(url: str) -> bool:
    try:
        host = httpx.URL(url).host
    except httpx.InvalidURL:
        return False
    return host in get_settings().connector_web_allowlist


def validate_urls(url_list: list[str]) -> None:
    """Rejects an unlisted host immediately at connector-create time,
    rather than silently at sync time -- a bad config should fail fast."""
    for url in url_list:
        if not _host_allowed(url):
            raise ValidationError(f"host not on the connector web allowlist: {url!r}")


class WebConnector(Connector):
    name = "web"

    async def authenticate(self, config: dict[str, Any]) -> dict[str, Any]:
        return config  # nothing to validate/refresh -- no credentials

    async def list_changes(
        self, config: dict[str, Any], cursor: str | None
    ) -> tuple[list[ChangeItem], str | None]:
        items = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for url in config.get("url_list", []):
                if not _host_allowed(url):
                    logger.warning("skipping url no longer on the allowlist: %s", url)
                    continue
                # A cheap HEAD request for a version signal, so the sync
                # loop can skip a full GET+checksum when nothing changed --
                # falls back to "" (always re-fetch) if the server offers
                # neither header.
                try:
                    response = await client.head(url, follow_redirects=True)
                    marker = (
                        response.headers.get("etag") or response.headers.get("last-modified") or ""
                    )
                except httpx.HTTPError:
                    marker = ""
                items.append(ChangeItem(external_id=url, cursor_marker=marker))
        return items, None  # cursor is never used by this connector

    async def fetch(self, config: dict[str, Any], item: ChangeItem) -> FetchedContent:
        if not _host_allowed(item.external_id):
            raise ValidationError(f"host not on the connector web allowlist: {item.external_id!r}")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(item.external_id, follow_redirects=True)
            response.raise_for_status()
        content_type = response.headers.get("content-type", "text/html").split(";")[0].strip()
        return FetchedContent(title=item.external_id, mime=content_type, content=response.content)

    async def map_acls(
        self, config: dict[str, Any], org_id: uuid.UUID, item: ChangeItem
    ) -> list[tuple[str, uuid.UUID]]:
        # No per-item permission data for an arbitrary URL -- everything
        # this connector syncs is, by construction, something the admin
        # who configured it wanted the whole org to see.
        return [("org", org_id)]
