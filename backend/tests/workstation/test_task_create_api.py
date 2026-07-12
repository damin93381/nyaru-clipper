from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from sqlmodel import select


def _reset_runtime_state() -> None:
    from app.db import reset_db_runtime

    reset_db_runtime()


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    # Given: an isolated workstation database and a configured local import root.
    database_path = tmp_path / "task-state.sqlite3"
    local_root = tmp_path / "trusted-media"
    (local_root / "vod").mkdir(parents=True)
    (local_root / "vod" / "example.mp4").write_bytes(b"fixture-media")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("APP_LOCAL_IMPORT_ROOTS", str(local_root))
    _reset_runtime_state()

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _root_id(client: TestClient) -> str:
    return str(client.get("/api/v2/sources/local").json()["roots"][0]["id"])


def _assert_created_task_records(task_id: str, *, expected_kind: str, expected_priority: int) -> None:
    from app.db import session_scope
    from app.models import MediaSource, PipelineRun, QueueEntry, StageRun, Task, TaskJob, TaskStage

    with session_scope() as session:
        task = session.get(Task, task_id)
        media_source = session.exec(select(MediaSource).where(MediaSource.task_id == task_id)).one()
        task_stages = session.exec(select(TaskStage).where(TaskStage.task_id == task_id).order_by(TaskStage.id)).all()
        task_job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        pipeline_run = session.exec(select(PipelineRun).where(PipelineRun.task_id == task_id)).one()
        stage_runs = session.exec(select(StageRun).where(StageRun.run_id == pipeline_run.id).order_by(StageRun.id)).all()
        queue_entry = session.get(QueueEntry, task_id)

        assert task is not None
        assert media_source.kind == expected_kind
        assert [stage.name for stage in task_stages] == ["ingest", "media_prep", "asr", "translation", "highlight", "export", "report"]
        assert task_job.stage_name == "ingest"
        assert pipeline_run.trigger == "create"
        assert [stage.name for stage in stage_runs] == ["ingest", "media_prep", "asr", "translation", "highlight", "export", "report"]
        assert queue_entry is not None
        assert queue_entry.priority == expected_priority
        assert queue_entry.state == "queued"


def test_v2_task_creation_persists_bilibili_source_and_complete_workstation_lifecycle(client: TestClient) -> None:
    # Given: a valid Bilibili source payload and the standard profile.
    payload = {
        "source": {"kind": "bilibili", "url": "https://www.bilibili.com/video/BV1abc"},
        "profile_id": "standard",
        "priority": 10,
    }

    # When: the task is created through the v2 API.
    response = client.post("/api/v2/tasks", json=payload)

    # Then: the source contract and every legacy/workstation lifecycle record are committed together.
    assert response.status_code == 201
    assert response.json()["profile_id"] == "standard"
    assert response.json()["priority"] == 10
    _assert_created_task_records(response.json()["task_id"], expected_kind="bilibili", expected_priority=10)


def test_v2_task_creation_revalidates_local_source_before_persisting_reference(client: TestClient) -> None:
    # Given: a supported local file selected through its opaque trusted-root identity.
    payload = {
        "source": {
            "kind": "local",
            "root_id": _root_id(client),
            "relative_path": "vod/example.mp4",
            "import_mode": "reference",
        },
        "profile_id": "standard",
        "priority": 0,
    }

    # When: a local-reference task is created.
    response = client.post("/api/v2/tasks", json=payload)

    # Then: a safe local MediaSource and complete pending lifecycle are persisted.
    assert response.status_code == 201
    task_id = response.json()["task_id"]
    _assert_created_task_records(task_id, expected_kind="local", expected_priority=0)

    from app.db import session_scope
    from app.models import MediaSource

    with session_scope() as session:
        source = session.exec(select(MediaSource).where(MediaSource.task_id == task_id)).one()
        assert source.locator == f"local://{payload['source']['root_id']}/vod/example.mp4"
        assert source.import_mode == "reference"


def test_v2_local_reference_task_runs_ingest_without_bilibili_download(client: TestClient, monkeypatch) -> None:
    # Given: a local task selected through the trusted catalog and non-ingest stages that complete in-process.
    payload = {
        "source": {
            "kind": "local",
            "root_id": _root_id(client),
            "relative_path": "vod/example.mp4",
            "import_mode": "reference",
        },
        "profile_id": "standard",
        "priority": 0,
    }
    create_response = client.post("/api/v2/tasks", json=payload)
    task_id = create_response.json()["task_id"]

    import app.services.task_runner as task_runner

    def downloader_must_not_run(*args, **kwargs) -> None:
        raise AssertionError("local reference ingestion must not call the Bilibili downloader")

    def complete_remaining_stage(session, current_task_id: str) -> None:
        assert current_task_id == task_id

    executors = dict(task_runner.STAGE_EXECUTORS)
    for stage_name in ("media_prep", "asr", "translation", "highlight", "export", "report"):
        executors[stage_name] = complete_remaining_stage
    monkeypatch.setattr(task_runner, "download_bilibili_vod", downloader_must_not_run)
    monkeypatch.setattr(task_runner, "STAGE_EXECUTORS", executors)

    # When: the canonical runner processes the local-reference task.
    from app.db import session_scope

    with session_scope() as session:
        result = task_runner.run_task_pipeline(session, task_id)

    # Then: ingest uses the server-side catalog reference and the pipeline can progress to completion.
    assert create_response.status_code == 201
    assert result.final_status == "success"
    assert result.completed_stages == ["ingest", "media_prep", "asr", "translation", "highlight", "export", "report"]


def test_v2_task_creation_rejects_non_url_bilibili_source_string(client: TestClient) -> None:
    # Given: a raw string that happens to contain a BV-like identifier but is not a URL.
    payload = {
        "source": {"kind": "bilibili", "url": "not-a-url-with-BV1arbitrary"},
        "profile_id": "standard",
        "priority": 0,
    }

    # When: the string is submitted to the v2 creation boundary.
    response = client.post("/api/v2/tasks", json=payload)

    # Then: v2 applies the same URL-boundary validation as inspect and v1 creation.
    assert response.status_code == 422
