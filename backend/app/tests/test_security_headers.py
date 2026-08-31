from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


def test_health_response_carries_security_headers() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in response.headers["permissions-policy"]
    csp = response.headers["content-security-policy"]
    assert csp == "default-src 'none'; frame-ancestors 'none'"


def test_hsts_absent_locally_but_present_outside_local(monkeypatch) -> None:
    client = TestClient(app)
    settings = get_settings()

    assert settings.environment == "local"
    response = client.get("/health")
    assert "strict-transport-security" not in response.headers

    monkeypatch.setattr(settings, "environment", "staging")
    response = client.get("/health")
    assert response.headers["strict-transport-security"] == "max-age=63072000; includeSubDomains"
