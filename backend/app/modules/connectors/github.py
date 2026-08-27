"""GitHub connector -- a real OAuth2 App flow (SPEC.md §26). Syncs a single
repo/branch's files. Incremental via the branch's latest commit SHA as the
sync cursor: if unchanged since the last sync, list_changes returns
immediately without listing the tree at all (the "cheap no-op").

The token-exchange/authorize-URL helpers here are connect-time-only
mechanics, not part of the Connector interface (base.py) itself -- they're
used once by connectors/service.py's OAuth callback handler, before a
Source (and therefore a token to authenticate() against) exists.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.modules.connectors.base import ChangeItem, Connector, FetchedContent

logger = logging.getLogger("helix.connectors")

_GITHUB_API = "https://api.github.com"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"


def build_authorize_url(redirect_uri: str, state: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.github_oauth_client_id,
        "redirect_uri": redirect_uri,
        "scope": "repo",
        "state": state,
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_token(code: str, redirect_uri: str) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            _TOKEN_URL,
            data={
                "client_id": settings.github_oauth_client_id,
                "client_secret": settings.github_oauth_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise UnauthorizedError(
            f"GitHub OAuth exchange failed: {body.get('error_description', body['error'])}"
        )
    return body


class GitHubConnector(Connector):
    name = "github"

    async def authenticate(self, config: dict[str, Any]) -> dict[str, Any]:
        oauth = config.get("oauth", {})
        expires_at = oauth.get("expires_at")
        refresh_token = oauth.get("refresh_token")
        # Classic GitHub OAuth App tokens don't expire by default -- this
        # branch only fires for a GitHub App/org configured to issue
        # expiring tokens, which is why refresh_token/expires_at are
        # optional fields in config, not assumed present.
        if not (
            expires_at and refresh_token and datetime.fromisoformat(expires_at) <= datetime.now(UTC)
        ):
            return config

        settings = get_settings()
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": settings.github_oauth_client_id,
                    "client_secret": settings.github_oauth_client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise UnauthorizedError("GitHub token refresh failed -- reconnect the connector")

        new_oauth = {**oauth, "access_token": body["access_token"]}
        if "refresh_token" in body:
            new_oauth["refresh_token"] = body["refresh_token"]
        if "expires_in" in body:
            new_oauth["expires_at"] = (
                datetime.now(UTC) + timedelta(seconds=body["expires_in"])
            ).isoformat()
        return {**config, "oauth": new_oauth}

    async def list_changes(
        self, config: dict[str, Any], cursor: str | None
    ) -> tuple[list[ChangeItem], str | None]:
        repo = config["repo"]
        branch = config.get("branch", "main")
        headers = {
            "Authorization": f"Bearer {config['oauth']['access_token']}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            commit_response = await client.get(f"{_GITHUB_API}/repos/{repo}/commits/{branch}")
            commit_response.raise_for_status()
            head_sha = commit_response.json()["sha"]

            if cursor == head_sha:
                return [], cursor  # cheap no-op -- nothing changed since the last sync

            tree_response = await client.get(
                f"{_GITHUB_API}/repos/{repo}/git/trees/{head_sha}", params={"recursive": "1"}
            )
            tree_response.raise_for_status()

        items = [
            ChangeItem(external_id=entry["path"], cursor_marker=entry["sha"])
            for entry in tree_response.json().get("tree", [])
            if entry["type"] == "blob"
        ]
        return items, head_sha

    async def fetch(self, config: dict[str, Any], item: ChangeItem) -> FetchedContent:
        repo = config["repo"]
        headers = {
            "Authorization": f"Bearer {config['oauth']['access_token']}",
            "Accept": "application/vnd.github.raw+json",
        }
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(f"{_GITHUB_API}/repos/{repo}/contents/{item.external_id}")
            response.raise_for_status()
        return FetchedContent(title=item.external_id, mime="text/plain", content=response.content)

    async def map_acls(
        self, config: dict[str, Any], org_id: uuid.UUID, item: ChangeItem
    ) -> list[tuple[str, uuid.UUID]]:
        # No GitHub-collaborator-to-Helix-user identity mapping in v1 (see
        # base.py's Connector.map_acls docstring) -- anyone in the org who
        # authorized this connector already has repo access via the stored
        # token, so org-wide visibility inside Helix isn't a broadening of
        # access, just a simplification of who can browse the synced copy.
        return [("org", org_id)]
