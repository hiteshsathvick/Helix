from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app import main as main_module
from app.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_200_when_dependencies_are_healthy() -> None:
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ready", "checks": {"database": True, "redis": True}}


def test_ready_returns_503_when_database_is_unreachable(monkeypatch) -> None:
    def _broken_connect(self: AsyncEngine):
        raise ConnectionError("simulated database outage")

    # AsyncEngine.connect is read-only on the instance (a descriptor on the
    # class) -- patch the class, not main_module.engine itself.
    monkeypatch.setattr(AsyncEngine, "connect", _broken_connect)

    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not ready"
    assert body["checks"]["database"] is False
    assert body["checks"]["redis"] is True


def test_ready_returns_503_when_redis_is_unreachable(monkeypatch) -> None:
    class _BrokenRedisClient:
        async def ping(self) -> None:
            raise ConnectionError("simulated redis outage")

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(main_module, "get_redis_client", lambda: _BrokenRedisClient())

    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not ready"
    assert body["checks"]["database"] is True
    assert body["checks"]["redis"] is False
