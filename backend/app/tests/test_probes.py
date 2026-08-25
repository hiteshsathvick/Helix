import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_create_and_list_probe_round_trips_through_postgres(client: TestClient) -> None:
    message = f"probe-{uuid.uuid4()}"

    create_response = client.post("/api/v1/probes", json={"message": message})
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["message"] == message
    assert "id" in created
    assert "created_at" in created

    list_response = client.get("/api/v1/probes")
    assert list_response.status_code == 200
    messages = [probe["message"] for probe in list_response.json()]
    assert message in messages


def test_create_probe_validation_error(client: TestClient) -> None:
    response = client.post("/api/v1/probes", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
