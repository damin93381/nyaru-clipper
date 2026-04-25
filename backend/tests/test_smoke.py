from fastapi.testclient import TestClient

from app.main import app


def test_fastapi_app_imports_and_responds() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "bilibili-vtuber-suite"}


def test_app_title_matches_workspace() -> None:
    assert app.title == "Bilibili VTuber Suite API"
