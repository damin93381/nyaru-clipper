from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select


CANONICAL_STAGES = [
    "ingest",
    "media_prep",
    "asr",
    "translation",
    "highlight",
    "export",
    "report",
]


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


@pytest.fixture()
def backend_env(tmp_path, monkeypatch) -> dict[str, Path | str]:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{db_path}")
    _reset_runtime_state()
    return {"data_dir": data_dir, "db_path": db_path}


@pytest.fixture()
def client(backend_env) -> TestClient:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_health_route_reports_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_task_persists_pending_canonical_stages_and_storage_layout(
    client: TestClient, backend_env: dict[str, Path | str]
) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1xx411c7mD?p=1"},
    )

    assert response.status_code == 201

    body = response.json()
    assert body["task_id"]
    assert body["status"] == "pending"
    assert body["source_url"] == "https://www.bilibili.com/video/BV1xx411c7mD?p=1"
    assert body["normalized_source_url"] == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert body["source_video_id"] == "BV1xx411c7mD"
    assert [stage["name"] for stage in body["stages"]] == CANONICAL_STAGES
    assert {stage["status"] for stage in body["stages"]} == {"pending"}

    task_id = body["task_id"]
    detail_response = client.get(f"/api/tasks/{task_id}")
    stages_response = client.get(f"/api/tasks/{task_id}/stages")
    artifacts_response = client.get(f"/api/tasks/{task_id}/artifacts")
    logs_response = client.get(f"/api/tasks/{task_id}/logs")

    assert detail_response.status_code == 200
    assert detail_response.json()["task_id"] == task_id

    assert stages_response.status_code == 200
    assert [stage["name"] for stage in stages_response.json()] == CANONICAL_STAGES

    assert artifacts_response.status_code == 200
    assert artifacts_response.json() == []

    assert logs_response.status_code == 200
    assert [entry["stage_name"] for entry in logs_response.json()] == CANONICAL_STAGES
    assert {entry["status"] for entry in logs_response.json()} == {"pending"}

    task_root = Path(backend_env["data_dir"]) / "tasks" / task_id
    assert task_root.is_dir()
    assert {path.name for path in task_root.iterdir()} == {"raw", "work", "exports", "reports", "logs"}


def test_duplicate_open_submission_returns_existing_task(client: TestClient) -> None:
    first = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1xx411c7mD?p=1"},
    )
    second = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1xx411c7mD"},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["task_id"] == first.json()["task_id"]
    assert second.json()["created"] is False


def test_task_artifact_paths_are_serialized_to_app_routes_and_served(client: TestClient, backend_env) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1xx411c7mD?p=1"},
    )
    task_id = response.json()["task_id"]

    from app.db import session_scope
    from app.services.storage import persist_artifact_metadata

    transcript_path = Path(backend_env["data_dir"]) / "tasks" / task_id / "work" / "asr-segments.json"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text('{"segments": []}', encoding="utf-8")

    with session_scope() as session:
        artifact = persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="asr",
            kind="transcript_json",
            path=transcript_path,
        )
        artifact_id = int(artifact.id)

    artifacts_response = client.get(f"/api/tasks/{task_id}/artifacts")

    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    assert artifacts == [
        {
            "id": artifact_id,
            "task_id": task_id,
            "stage_name": "asr",
            "kind": "transcript_json",
            "path": f"/api/tasks/{task_id}/artifacts/{artifact_id}/content/asr-segments.json",
            "metadata_json": "{}",
        }
    ]

    content_response = client.get(artifacts[0]["path"])

    assert content_response.status_code == 200
    assert content_response.json() == {"segments": []}
    assert "attachment; filename=\"asr-segments.json\"" in content_response.headers["content-disposition"]


def test_retry_resets_failed_stage_and_downstream_stages_to_pending(client: TestClient) -> None:
    create_response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1ab411c7mE"},
    )
    task_id = create_response.json()["task_id"]

    from app.db import session_scope
    from app.models import TaskStage

    with session_scope() as session:
        task_stages = session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
        for stage in task_stages:
            if stage.name in {"ingest", "media_prep", "asr"}:
                stage.status = "success"
            elif stage.name in {"translation", "highlight", "export", "report"}:
                stage.status = "failed" if stage.name == "translation" else "skipped"
        session.add_all(task_stages)

    retry_response = client.post(f"/api/tasks/{task_id}/retry", json={"stage_name": "translation"})

    assert retry_response.status_code == 202
    assert retry_response.json() == {"task_id": task_id, "retry_stage": "translation", "status": "pending"}

    stages_response = client.get(f"/api/tasks/{task_id}/stages")
    stage_statuses = {stage["name"]: stage["status"] for stage in stages_response.json()}

    assert stage_statuses == {
        "ingest": "success",
        "media_prep": "success",
        "asr": "success",
        "translation": "pending",
        "highlight": "pending",
        "export": "pending",
        "report": "pending",
    }


def test_worker_claims_only_one_active_gpu_bound_job_at_a_time(client: TestClient) -> None:
    first_task = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1cd411c7mF"},
    ).json()["task_id"]
    second_task = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1ef411c7mG"},
    ).json()["task_id"]

    from app.worker import claim_next_job, complete_job

    claimed_first = claim_next_job()
    claimed_second = claim_next_job()

    assert claimed_first is not None
    assert claimed_first.task_id == first_task
    assert claimed_second is None

    complete_job(claimed_first.task_id, success=True)
    claimed_after_completion = claim_next_job()

    assert claimed_after_completion is not None
    assert claimed_after_completion.task_id == second_task
