"""Helix public API client -- a stub (SPEC.md §18 roadmap item), not a
published package. Demonstrates the auth header and the three endpoints
Phase 18 ships: search, list documents, upload a document. Copy/adapt
rather than `pip install` -- there is no packaging (setup.py/pyproject.toml)
here on purpose.

Usage:
    client = HelixClient(base_url="https://your-helix-instance.example.com", api_key="hx_...")
    results = client.search("quarterly report")
    docs = client.list_documents()
    client.upload_document("notes.txt", b"some content", "text/plain")

Get an api_key from the dashboard: Org -> API Keys -> Create key. Each key
is scoped (search:read / documents:read / documents:write) -- a call
against an endpoint the key wasn't granted returns 403.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


class HelixApiError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"Helix API error {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class HelixClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def _request(
        self, method: str, path: str, *, body: bytes | None = None, headers: dict[str, str] | None = None
    ) -> Any:
        url = f"{self.base_url}/api/v1/public{path}"
        request = urllib.request.Request(
            url, data=body, headers={**self._headers, **(headers or {})}, method=method
        )
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise HelixApiError(exc.code, exc.read().decode()) from exc

    def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        """Requires the search:read scope."""
        params = urllib.parse.urlencode({"q": query, "limit": limit})
        return self._request("GET", f"/search?{params}")

    def list_documents(self) -> list[dict[str, Any]]:
        """Requires the documents:read scope."""
        return self._request("GET", "/documents")

    def upload_document(self, filename: str, content: bytes, content_type: str) -> dict[str, Any]:
        """Requires the documents:write scope. Builds a minimal multipart
        body by hand -- a real client would reach for `requests` here;
        this stub sticks to the standard library on purpose."""
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        return self._request(
            "POST",
            "/documents",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
