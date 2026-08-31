"""Contract test for the public API subset (SPEC.md §18, Phase 20).

`sdk/python/helix_client.py` is the one real external consumer of this
surface -- it hardcodes three paths/methods against `{base_url}/api/v1/public`.
This asserts the generated OpenAPI schema still exposes exactly those paths,
with the query/multipart/response shapes the SDK stub assumes, so a change
that silently breaks the public API surface fails here instead of only being
caught by someone manually re-running the SDK stub (as Phase 18's shipping
notes describe doing once, by hand).
"""

from fastapi.testclient import TestClient

from app.main import app


def _openapi_schema() -> dict:
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_public_search_contract():
    schema = _openapi_schema()
    operation = schema["paths"]["/api/v1/public/search"]["get"]
    param_names = {p["name"] for p in operation["parameters"]}
    # The SDK builds `?q=<query>&limit=<limit>` by hand (helix_client.py) --
    # renaming either query param would silently break every existing
    # integration with no compile-time warning.
    assert {"q", "limit", "cursor"} <= param_names
    assert "200" in operation["responses"]


def test_public_list_documents_contract():
    schema = _openapi_schema()
    operation = schema["paths"]["/api/v1/public/documents"]["get"]
    assert "200" in operation["responses"]
    # response_model=list[DocumentRead] -- the SDK returns this straight to
    # the caller as a list, so a change to an object/paginated envelope
    # would be a breaking change worth catching here.
    schema_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema_ref["type"] == "array"


def test_public_upload_document_contract():
    schema = _openapi_schema()
    operation = schema["paths"]["/api/v1/public/documents"]["post"]
    assert operation["responses"]["201"]
    request_body = operation["requestBody"]["content"]
    # The SDK hand-builds a multipart/form-data body with a "file" field
    # (helix_client.py's upload_document) -- this is the one shape it must
    # keep matching.
    assert "multipart/form-data" in request_body
