import json
from datetime import datetime, timezone
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


def test_task_detail_failure_recovery_reports_asr_missing_model(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1missingmodel001"},
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]

    from app.db import session_scope
    from app.models import Task, TaskStage

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "failed"
        session.add(task)

        asr_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        asr_stage.status = "failed"
        asr_stage.summary = "missing_model"
        session.add(asr_stage)

    detail_response = client.get(f"/api/tasks/{task_id}")

    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["failure_recovery"]["stage"] == "asr"
    assert body["failure_recovery"]["kind"] == "missing_model"
    assert [model["key"] for model in body["failure_recovery"]["models"]] == ["whisperx", "alignment"]


def test_task_detail_exposes_failure_code_and_recovery_actions(
    client: TestClient, backend_env: dict[str, Path | str]
) -> None:
    from app.db import session_scope
    from app.models import Artifact, Task, TaskStage

    def create_failed_task(source_id: str, failed_stage_name: str, *, summary: str | None = None) -> str:
        response = client.post(
            "/api/tasks",
            json={"source_url": f"https://www.bilibili.com/video/{source_id}"},
        )
        assert response.status_code == 201
        task_id = response.json()["task_id"]
        with session_scope() as session:
            task = session.get(Task, task_id)
            assert task is not None
            task.status = "failed"
            session.add(task)

            stages = session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
            failed_index = CANONICAL_STAGES.index(failed_stage_name)
            for stage in stages:
                stage_index = CANONICAL_STAGES.index(stage.name)
                if stage_index < failed_index:
                    stage.status = "success"
                elif stage.name == failed_stage_name:
                    stage.status = "failed"
                    stage.summary = summary or f"{failed_stage_name}_failed"
                else:
                    stage.status = "skipped"
                session.add(stage)
        return task_id

    generic_task_id = create_failed_task("BV1genericfail001", "translation", summary="provider_timeout")
    ready_video = Path(backend_env["data_dir"]) / "tasks" / generic_task_id / "raw" / "source.mp4"
    ready_video.parent.mkdir(parents=True, exist_ok=True)
    ready_video.write_text("fake video", encoding="utf-8")
    (Path(backend_env["data_dir"]) / "tasks" / generic_task_id / "logs" / "translation.log").write_text(
        "provider timed out with token abc123\n", encoding="utf-8"
    )
    with session_scope() as session:
        artifact = Artifact(
            task_id=generic_task_id,
            stage_name="ingest",
            kind="source_video",
            path=str(ready_video),
            metadata_json='{"duration_seconds": 12}',
        )
        session.add(artifact)
        session.flush()
        ready_artifact_id = int(artifact.id)

    generic_response = client.get(f"/api/tasks/{generic_task_id}")
    assert generic_response.status_code == 200
    generic_body = generic_response.json()
    assert generic_body["failure_code"] == "unknown_failure"
    assert generic_body["recovery_actions"] == [
        {
            "id": "retry_stage",
            "label_key": "retry_stage",
            "description_key": "retry_stage",
            "enabled": True,
            "disabled_reason": None,
            "method": "POST",
            "endpoint": f"/api/tasks/{generic_task_id}/retry",
            "payload": {"stage_name": "translation"},
            "confirmation_required": False,
            "success_behavior": "poll_task",
        }
    ]
    assert generic_body["artifact_readiness"] == [
        {
            "stage_name": "ingest",
            "kind": "source_video",
            "status": "ready",
            "artifact_id": ready_artifact_id,
            "path": f"/api/tasks/{generic_task_id}/artifacts/{ready_artifact_id}/content/source.mp4",
        },
        {
            "stage_name": "media_prep",
            "kind": "prepared_audio",
            "status": "missing",
            "artifact_id": None,
            "path": None,
        },
        {
            "stage_name": "asr",
            "kind": "transcript_json",
            "status": "missing",
            "artifact_id": None,
            "path": None,
        },
        {
            "stage_name": "translation",
            "kind": "translated_segments",
            "status": "failed",
            "artifact_id": None,
            "path": None,
        },
    ]

    logs_response = client.get(f"/api/tasks/{generic_task_id}/logs")
    assert logs_response.status_code == 200
    translation_log = next(entry for entry in logs_response.json() if entry["stage_name"] == "translation")
    assert translation_log == {
        "stage_name": "translation",
        "status": "failed",
        "summary": "provider timed out with token abc123",
        "display_label": "Translation",
        "safe_summary": "provider timed out with token [redacted]",
        "log_path": f"/data/tasks/{generic_task_id}/logs/translation.log",
    }

    asr_task_id = create_failed_task("BV1asrmissing001", "asr", summary="missing_model")
    asr_response = client.get(f"/api/tasks/{asr_task_id}")
    assert asr_response.status_code == 200
    asr_body = asr_response.json()
    assert asr_body["failure_code"] == "asr_missing_model"
    assert asr_body["failure_recovery"]["kind"] == "missing_model"
    assert [action["id"] for action in asr_body["recovery_actions"]] == ["download_asr_model", "retry_stage"]
    assert asr_body["recovery_actions"][0] == {
        "id": "download_asr_model",
        "label_key": "download_asr_model",
        "description_key": "download_asr_model",
        "enabled": True,
        "disabled_reason": None,
        "method": "POST",
        "endpoint": f"/api/tasks/{asr_task_id}/asr/models/download",
        "payload": {"model_keys": ["whisperx", "alignment"]},
        "confirmation_required": False,
        "success_behavior": "retry_stage_after_success",
    }

    cancelled_response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1cancelled001"},
    )
    assert cancelled_response.status_code == 201
    cancelled_task_id = cancelled_response.json()["task_id"]
    with session_scope() as session:
        task = session.get(Task, cancelled_task_id)
        assert task is not None
        task.status = "cancelled"
        session.add(task)

    cancelled_detail = client.get(f"/api/tasks/{cancelled_task_id}")
    assert cancelled_detail.status_code == 200
    assert cancelled_detail.json()["failure_code"] is None
    assert [action for action in cancelled_detail.json()["recovery_actions"] if action["enabled"]] == []


def test_task_detail_omits_execution_progress_when_no_tracked_row_exists(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1noprogress001"},
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]

    detail_response = client.get(f"/api/tasks/{task_id}")

    assert detail_response.status_code == 200
    assert "execution_progress" not in detail_response.json()


def test_task_detail_includes_execution_progress_for_active_asr_task(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1progress001"},
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]

    import app.models as app_models
    from app.db import session_scope

    progress_model = getattr(app_models, "TaskExecutionProgress", None)
    assert progress_model is not None

    phase_started_at = datetime(2026, 5, 3, 5, 0, tzinfo=timezone.utc)
    heartbeat_at = datetime(2026, 5, 3, 5, 1, tzinfo=timezone.utc)
    phase_timings = [
        {"name": "model_load", "status": "success", "elapsed_ms": 1234},
        {"name": "vad", "status": "success", "elapsed_ms": 4567},
        {"name": "transcribe", "status": "running", "elapsed_ms": 8901},
        {"name": "align", "status": "pending", "elapsed_ms": None},
        {"name": "persist", "status": "pending", "elapsed_ms": None},
    ]

    with session_scope() as session:
        session.add(
            progress_model(
                task_id=task_id,
                stage_name="asr",
                current_phase="transcribe",
                phase_index=3,
                phase_count=5,
                latest_message="transcribe running",
                phase_started_at=phase_started_at,
                heartbeat_at=heartbeat_at,
                phase_timings_json=json.dumps(phase_timings),
            )
        )

    detail_response = client.get(f"/api/tasks/{task_id}")

    assert detail_response.status_code == 200
    assert detail_response.json()["execution_progress"] == {
        "stage_name": "asr",
        "current_phase": "transcribe",
        "phase_index": 3,
        "phase_count": 5,
        "phase_started_at": "2026-05-03T05:00:00+00:00",
        "heartbeat_at": "2026-05-03T05:01:00+00:00",
        "latest_message": "transcribe running",
        "phases": phase_timings,
    }


def test_task_cancel_overlay_and_force_kill_require_tracked_asr_process_group(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1cancelcontrol001"},
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]

    from app.db import session_scope
    from app.models import Task, TaskExecutionControl, TaskJob, TaskStage

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "running"
        session.add(task)

        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        job.status = "running"
        job.stage_name = "asr"
        session.add(job)

        asr_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        asr_stage.status = "running"
        session.add(asr_stage)

        session.add(
            TaskExecutionControl(
                task_id=task_id,
                execution_token="token-asr-cancel",
                active_process_group_id=None,
                cancel_requested=False,
                force_kill_requested=False,
            )
        )

    cancel_response = client.post(f"/api/tasks/{task_id}/cancel")
    assert cancel_response.status_code == 202

    detail_response = client.get(f"/api/tasks/{task_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["status"] == "cancel_requested"
    assert next(stage for stage in detail_payload["stages"] if stage["name"] == "asr")["status"] == "running"

    force_kill_response = client.post(f"/api/tasks/{task_id}/force-kill")
    assert force_kill_response.status_code == 409

    with session_scope() as session:
        control = session.get(TaskExecutionControl, task_id)
        assert control is not None
        assert control.cancel_requested is True
        control.active_process_group_id = 424242
        session.add(control)

    force_kill_response = client.post(f"/api/tasks/{task_id}/force-kill")
    assert force_kill_response.status_code == 202

    with session_scope() as session:
        control = session.get(TaskExecutionControl, task_id)
        assert control is not None
        assert control.force_kill_requested is True


def test_task_force_kill_rejects_non_asr_stage_even_with_tracked_process_group(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1forcekillmedia001"},
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]

    from app.db import session_scope
    from app.models import Task, TaskExecutionControl, TaskJob, TaskStage

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "running"
        session.add(task)

        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        job.status = "running"
        job.stage_name = "media_prep"
        session.add(job)

        media_prep_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "media_prep")
        ).one()
        media_prep_stage.status = "running"
        session.add(media_prep_stage)

        session.add(
            TaskExecutionControl(
                task_id=task_id,
                execution_token="token-media-prep-force-kill",
                active_process_group_id=31337,
                cancel_requested=False,
                force_kill_requested=False,
            )
        )

    force_kill_response = client.post(f"/api/tasks/{task_id}/force-kill")
    assert force_kill_response.status_code == 409

    with session_scope() as session:
        control = session.get(TaskExecutionControl, task_id)
        assert control is not None
        assert control.force_kill_requested is False


def test_task_force_kill_rejects_non_running_asr_even_with_tracked_process_group(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1forcekillstale001"},
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]

    from app.db import session_scope
    from app.models import Task, TaskExecutionControl, TaskJob, TaskStage

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "failed"
        session.add(task)

        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        job.status = "failed"
        job.stage_name = "asr"
        session.add(job)

        asr_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        asr_stage.status = "failed"
        session.add(asr_stage)

        session.add(
            TaskExecutionControl(
                task_id=task_id,
                execution_token="token-stale-asr-force-kill",
                active_process_group_id=31338,
                cancel_requested=False,
                force_kill_requested=False,
            )
        )

    force_kill_response = client.post(f"/api/tasks/{task_id}/force-kill")
    assert force_kill_response.status_code == 409

    with session_scope() as session:
        control = session.get(TaskExecutionControl, task_id)
        assert control is not None
        assert control.force_kill_requested is False


def test_task_cancel_rejects_stale_inactive_control_row(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1cancelstale001"},
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]

    from app.db import session_scope
    from app.models import Task, TaskExecutionControl, TaskJob, TaskStage

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "failed"
        session.add(task)

        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        job.status = "failed"
        job.stage_name = "asr"
        session.add(job)

        asr_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        asr_stage.status = "failed"
        session.add(asr_stage)

        session.add(
            TaskExecutionControl(
                task_id=task_id,
                execution_token="token-stale-asr-cancel",
                active_process_group_id=424243,
                cancel_requested=False,
                force_kill_requested=False,
            )
        )

    cancel_response = client.post(f"/api/tasks/{task_id}/cancel")
    assert cancel_response.status_code == 409

    with session_scope() as session:
        control = session.get(TaskExecutionControl, task_id)
        assert control is not None
        assert control.cancel_requested is False


def test_asr_model_download_returns_accepted_model_status_payload(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1downloadmodels001"},
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]

    from app.db import session_scope
    from app.models import Task, TaskStage

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "failed"
        session.add(task)

        asr_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        asr_stage.status = "failed"
        asr_stage.summary = "missing_model"
        session.add(asr_stage)

    download_response = client.post(
        f"/api/tasks/{task_id}/asr/models/download",
        json={"model_keys": ["whisperx"]},
    )

    assert download_response.status_code == 202
    body = download_response.json()
    assert body["stage"] == "asr"
    assert body["kind"] == "missing_model"
    assert [model["key"] for model in body["models"]] == ["whisperx"]


def test_asr_model_download_rejects_invalid_model_keys(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1invalidmodelkey001"},
    )
    task_id = response.json()["task_id"]

    download_response = client.post(
        f"/api/tasks/{task_id}/asr/models/download",
        json={"model_keys": ["not-a-real-model"]},
    )

    assert download_response.status_code == 422


def test_asr_model_download_requires_missing_model_failure_state(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        json={"source_url": "https://www.bilibili.com/video/BV1downloadstate001"},
    )
    task_id = response.json()["task_id"]

    download_response = client.post(
        f"/api/tasks/{task_id}/asr/models/download",
        json={"model_keys": ["whisperx"]},
    )

    assert download_response.status_code == 409
