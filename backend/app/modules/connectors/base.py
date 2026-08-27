"""Connector framework (SPEC.md §26). A Connector wraps one external
system; app/modules/connectors/service.py's sync loop drives any Connector
identically via this interface, never touching a connector's own HTTP/API
details directly.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChangeItem:
    # Stable identity within this source -- a URL for the web connector, a
    # repo-relative path for GitHub. Matches Document.external_id.
    external_id: str
    # A cheap-to-compare version signal (a blob SHA, an ETag) -- NOT the
    # content itself. list_changes must stay cheap even for a large source;
    # content is only fetched for items the sync loop actually decides to
    # process.
    cursor_marker: str


@dataclass(frozen=True)
class FetchedContent:
    title: str
    mime: str
    content: bytes


class Connector(ABC):
    name: str

    @abstractmethod
    async def authenticate(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validates (and, for OAuth connectors, refreshes) credentials in
        `config` -- the decrypted view of Source.config. Returns the config
        to persist back (unchanged for the web connector; a refreshed
        access token for GitHub if the stored one had expired). Called both
        at connect time and at the start of every sync."""

    @abstractmethod
    async def list_changes(
        self, config: dict[str, Any], cursor: str | None
    ) -> tuple[list[ChangeItem], str | None]:
        """Returns items that may have changed since `cursor`, plus the new
        cursor to persist. An empty list with the same cursor back means
        "nothing changed" -- checked cheaply, without listing every item,
        where the connector can (see GitHubConnector)."""

    @abstractmethod
    async def fetch(self, config: dict[str, Any], item: ChangeItem) -> FetchedContent:
        """Fetches the actual bytes for one item."""

    @abstractmethod
    async def map_acls(
        self, config: dict[str, Any], org_id: uuid.UUID, item: ChangeItem
    ) -> list[tuple[str, uuid.UUID]]:
        """Returns (principal_type, principal_id) pairs matching
        DocumentACL's shape. v1's two connectors both return org-wide
        visibility -- see their own docstrings for why -- but this is a
        real per-connector method a future connector with actual
        per-item permission data can override."""
