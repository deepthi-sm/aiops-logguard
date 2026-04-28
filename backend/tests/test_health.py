from fastapi.testclient import TestClient

from api.main import app


def test_health_returns_ok():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str)
    assert isinstance(body["uptime_s"], int)
    assert body["uptime_s"] >= 0
