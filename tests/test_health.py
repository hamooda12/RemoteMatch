from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "RemoteMatch",
        "environment": "development",
        "version": "0.1.0",
    }


def test_database_health_endpoint() -> None:
    response = client.get("/api/v1/health/database")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "reachable",
    }
