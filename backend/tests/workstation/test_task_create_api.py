from __future__ import annotations

import json
from pathlib import Path
import subprocess

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
        test_client.local_root = local_root  # type: ignore[attr-defined]
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


def test_v2_local_copy_task_creates_a_managed_task_copy_before_media_preparation(
    client: TestClient,
    monkeypatch,
) -> None:
    # Given: a trusted local source selected for a task-owned copy.
    payload = {
        "source": {
            "kind": "local",
            "root_id": _root_id(client),
            "relative_path": "vod/example.mp4",
            "import_mode": "copy",
        },
        "profile_id": "standard",
        "priority": 0,
    }

    # When: the source is created and the canonical ingest stage runs.
    create_response = client.post("/api/v2/tasks", json=payload)

    # Then: creation accepts the mode and ingest copies from the trusted root without using the downloader.
    assert create_response.status_code == 201
    task_id = create_response.json()["task_id"]

    import app.services.task_runner as task_runner

    def downloader_must_not_run(*args, **kwargs) -> None:
        raise AssertionError("local copy ingestion must not call the Bilibili downloader")

    monkeypatch.setattr(task_runner, "download_bilibili_vod", downloader_must_not_run)
    from app.db import session_scope
    from app.models import Artifact, MediaSource

    with session_scope() as session:
        task_runner._execute_ingest(session, task_id)
        source = session.exec(select(MediaSource).where(MediaSource.task_id == task_id)).one()
        artifact = session.exec(
            select(Artifact).where(Artifact.task_id == task_id, Artifact.stage_name == "ingest", Artifact.kind == "source_video")
        ).one()
        import_mode = source.import_mode
        artifact_path = artifact.path
        artifact_metadata = artifact.metadata_json

    assert import_mode == "copy"
    copied_path = Path(artifact_path)
    assert copied_path.name == "source.mp4"
    assert copied_path.read_bytes() == b"fixture-media"
    assert str(client.local_root) not in artifact_metadata


def test_v2_local_copy_task_fails_ingest_with_a_safe_diagnostic_if_the_source_is_removed(
    client: TestClient,
) -> None:
    # Given: a valid local-copy task whose selected source disappears before the worker claims it.
    payload = {
        "source": {
            "kind": "local",
            "root_id": _root_id(client),
            "relative_path": "vod/example.mp4",
            "import_mode": "copy",
        },
        "profile_id": "standard",
        "priority": 0,
    }
    create_response = client.post("/api/v2/tasks", json=payload)
    task_id = create_response.json()["task_id"]
    (client.local_root / "vod" / "example.mp4").unlink()

    # When: the pipeline reaches ingest after the source has left its trusted root.
    import app.services.task_runner as task_runner

    from app.db import session_scope
    from app.models import TaskStage
    from app.services.source_catalog import SourceCatalogError

    with session_scope() as session:
        with pytest.raises(SourceCatalogError, match="Local path does not exist"):
            task_runner.run_task_pipeline(session, task_id)
        ingest = session.exec(select(TaskStage).where(TaskStage.task_id == task_id, TaskStage.name == "ingest")).one()
        summary = ingest.summary

    # Then: the failure is actionable but does not disclose the configured host path.
    assert create_response.status_code == 201
    assert summary == "Local path does not exist"
    assert str(client.local_root) not in summary


def test_v2_local_copy_task_sanitizes_copy_io_errors_before_persisting_stage_failure(
    client: TestClient,
    monkeypatch,
) -> None:
    # Given: a local copy whose filesystem operation reports a trusted host path.
    payload = {
        "source": {
            "kind": "local",
            "root_id": _root_id(client),
            "relative_path": "vod/example.mp4",
            "import_mode": "copy",
        },
        "profile_id": "standard",
        "priority": 0,
    }
    task_id = client.post("/api/v2/tasks", json=payload).json()["task_id"]

    import app.services.task_runner as task_runner

    def fail_copy(source: Path, destination: Path) -> None:
        raise OSError(f"Cannot read {source}")

    monkeypatch.setattr(task_runner.shutil, "copy2", fail_copy)
    from app.db import session_scope
    from app.models import TaskStage
    from app.services.storage import log_file_for_stage

    # When: ingest attempts the task-owned copy.
    with session_scope() as session:
        with pytest.raises(RuntimeError, match="Unable to copy local source video"):
            task_runner.run_task_pipeline(session, task_id)
        ingest = session.exec(select(TaskStage).where(TaskStage.task_id == task_id, TaskStage.name == "ingest")).one()
        summary = ingest.summary
        log_contents = log_file_for_stage(task_id, "ingest").read_text(encoding="utf-8")

    # Then: durable stage state contains a stable diagnostic, never the trusted source path.
    assert summary == "Unable to copy local source video"
    assert str(client.local_root) not in summary
    assert "Unable to copy local source video" in log_contents
    assert str(client.local_root) not in log_contents


def test_v2_local_reference_task_keeps_trusted_root_paths_out_of_persisted_and_returned_data(
    client: TestClient,
    monkeypatch,
) -> None:
    # Given: a local task selected through the trusted catalog, with media tools that disclose their input path.
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

    def run_media_command(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps({"format": {"filename": str(client.local_root / "vod" / "example.mp4"), "duration": "42"}}),
                stderr="",
            )
        if args[0] == "ffmpeg":
            output_path = Path(args[-1])
            output_path.write_bytes(b"wav")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    executors = dict(task_runner.STAGE_EXECUTORS)
    for stage_name in ("asr", "translation", "highlight", "export"):
        executors[stage_name] = complete_remaining_stage
    monkeypatch.setattr(task_runner, "download_bilibili_vod", downloader_must_not_run)
    monkeypatch.setattr(task_runner, "STAGE_EXECUTORS", executors)
    monkeypatch.setattr("app.services.pipeline_support.subprocess.run", run_media_command)

    # When: the canonical runner processes the local-reference task.
    from app.db import session_scope

    with session_scope() as session:
        result = task_runner.run_task_pipeline(session, task_id)

    # Then: runtime resolution remains server-side while stored and returned data retain only the opaque reference.
    assert create_response.status_code == 201
    assert result.final_status == "success"
    assert result.completed_stages == ["ingest", "media_prep", "asr", "translation", "highlight", "export", "report"]

    trusted_root = str(client.local_root)  # type: ignore[attr-defined]
    from app.db import session_scope
    from app.models import Artifact

    with session_scope() as session:
        artifacts = session.exec(select(Artifact).where(Artifact.task_id == task_id)).all()
        report = next(artifact for artifact in artifacts if artifact.kind == "task_report_markdown")
        report_path = report.path
        persisted_artifact_data = "\n".join(f"{artifact.path}\n{artifact.metadata_json}" for artifact in artifacts)

    report_text = Path(report_path).read_text(encoding="utf-8")
    api_artifacts = client.get(f"/api/tasks/{task_id}/artifacts")
    v2_overview = client.get(f"/api/v2/tasks/{task_id}")
    logs = client.get(f"/api/tasks/{task_id}/logs")

    assert trusted_root not in persisted_artifact_data
    assert trusted_root not in report_text
    assert trusted_root not in api_artifacts.text
    assert trusted_root not in v2_overview.text
    assert trusted_root not in logs.text


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


def test_v2_task_creation_rejects_bv_identifier_on_an_untrusted_host(client: TestClient) -> None:
    # Given: an arbitrary HTTPS host with a BV-shaped path segment.
    payload = {
        "source": {"kind": "bilibili", "url": "https://example.invalid/BV1abc"},
        "profile_id": "standard",
        "priority": 0,
    }

    # When: the task source crosses the v2 creation boundary.
    response = client.post("/api/v2/tasks", json=payload)

    # Then: creation rejects it instead of normalizing the attacker-controlled host into Bilibili.
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported Bilibili source URL"
