from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import ConflictError, NotFoundError, register_exception_handlers


def build_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom-not-found")
    async def boom_not_found() -> None:
        raise NotFoundError("widget not found", details={"widget_id": "123"})

    @app.get("/boom-conflict")
    async def boom_conflict() -> None:
        raise ConflictError("widget already exists")

    @app.get("/boom-unhandled")
    async def boom_unhandled() -> None:
        raise RuntimeError("something exploded")

    @app.post("/boom-validation")
    async def boom_validation(count: int) -> dict[str, int]:
        return {"count": count}

    return app


client = TestClient(build_test_app(), raise_server_exceptions=False)


def test_domain_error_maps_to_envelope() -> None:
    response = client.get("/boom-not-found")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "widget not found"
    assert body["error"]["details"] == {"widget_id": "123"}


def test_conflict_error_status_code() -> None:
    response = client.get("/boom-conflict")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_validation_error_envelope() -> None:
    response = client.post("/boom-validation")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "errors" in body["error"]["details"]


def test_unhandled_exception_returns_500_with_correlation_id_and_no_internals() -> None:
    response = client.get("/boom-unhandled")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "correlation_id" in body["error"]["details"]
    assert "something exploded" not in response.text
    assert "RuntimeError" not in response.text


def test_unknown_route_uses_error_envelope() -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"
