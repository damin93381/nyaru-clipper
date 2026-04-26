def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def test_app_startup_import_and_health_route_work_without_docker(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{db_path}")
    _reset_runtime_state()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["storage"] == "ok"
    assert response.json()["database"] == "ok"
    runtime_capabilities = response.json()["runtime_capabilities"]

    assert list(runtime_capabilities.keys()) == [
        "status",
        "detected_profile",
        "accelerator",
        "warnings",
        "issue_codes",
    ]
    assert list(runtime_capabilities["accelerator"].keys()) == [
        "available",
        "backend",
        "device_count",
        "device_name",
        "torch_build_family",
    ]
