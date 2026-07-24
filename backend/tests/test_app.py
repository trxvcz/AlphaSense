from fastapi.testclient import TestClient

from app.main import app


def test_openapi_schema_available() -> None:
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Portfel v2 API"
