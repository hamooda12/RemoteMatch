from fastapi.testclient import TestClient

from app.core.config import get_settings


def test_health_endpoint(client: TestClient) -> None:
    settings = get_settings()

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "RemoteMatch",
        "environment": settings.environment,
        "version": "0.1.0",
    }


def test_database_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/health/database")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "reachable",
    }
