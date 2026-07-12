from __future__ import annotations

import json
import subprocess
import time
from datetime import timedelta
from pathlib import Path

import pytest
from sqlmodel import select


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


def _create_task(source_url: str) -> str:
    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, source_url)
        return payload["task_id"]


def _warning_payload() -> dict[str, object]:
    return {
        "status": "error",
        "detected_profile": "cpu-only",
        "platform": {
            "is_wsl": True,
            "machine": "x86_64",
            "release": "6.8.0-microsoft-standard-WSL2",
            "system": "linux",
            "version": "#1 SMP PREEMPT_DYNAMIC",
        },
        "accelerator": {
            "available": False,
            "backend": "cpu",
            "cuda_version": "12.8",
            "device_count": 0,
            "device_name": None,
            "hip_version": None,
            "kind": "cpu",
            "torch_available": True,
            "torch_build_family": "cuda",
            "torch_version": "2.8.0+cu128",
        },
        "dependencies": {"tools": {}, "python": {}},
        "warnings": [
            "WSL detected a CUDA-built torch wheel. Install the dedicated WSL ROCm backend environment instead.",
            "GPU runtime was not detected; backend is operating in cpu-only mode.",
            "System tool 'ffprobe' was not found on PATH.",
        ],
        "issues": [
            {
                "code": "wrong_torch_build_cuda_on_wsl",
                "message": "WSL host is using a CUDA-built torch wheel instead of the dedicated ROCm build.",
                "severity": "error",
            }
        ],
    }


def _extract_runtime_summary(summary: str | None) -> dict[str, object]:
    assert summary is not None
    prefix = "worker_preflight_runtime="
    assert summary.startswith(prefix)
    return json.loads(summary.removeprefix(prefix))


def test_worker_iteration_surfaces_runtime_warnings_in_stage_log_summary(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1workerwarn001")

    from app.db import session_scope
    from app.models import Task
    from app.repositories.tasks import list_task_log_summaries
    from app.worker import run_worker_iteration
    import app.services.task_runner as task_runner

    called: list[str] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str):
            assert current_task_id == task_id
            called.append(stage_name)
            if stage_name == "ingest":
                task = session.get(Task, current_task_id)
                assert task is not None
                task.source_video_id = "BV1workerwarn001"
                session.add(task)

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )
    monkeypatch.setattr("app.services.capability_checks.get_runtime_capabilities", _warning_payload)

    claimed = run_worker_iteration()

    assert claimed is not None
    assert claimed.task_id == task_id
    assert claimed.stage_name == "ingest"
    assert called == list(task_runner.CANONICAL_STAGE_ORDER)

    with session_scope() as session:
        log_summaries = list_task_log_summaries(session, task_id)

    assert log_summaries is not None
    ingest_summary = next(entry["summary"] for entry in log_summaries if entry["stage_name"] == "ingest")
    assert _extract_runtime_summary(ingest_summary) == {
        "accelerator": {
            "available": False,
            "backend": "cpu",
            "device_count": 0,
            "device_name": None,
            "torch_build_family": "cuda",
        },
        "detected_profile": "cpu-only",
        "issue_codes": ["wrong_torch_build_cuda_on_wsl"],
        "issues": [
            {
                "code": "wrong_torch_build_cuda_on_wsl",
                "message": "WSL host is using a CUDA-built torch wheel instead of the dedicated ROCm build.",
                "severity": "error",
            }
        ],
        "status": "error",
        "warnings": [
            "WSL detected a CUDA-built torch wheel. Install the dedicated WSL ROCm backend environment instead.",
            "GPU runtime was not detected; backend is operating in cpu-only mode.",
            "System tool 'ffprobe' was not found on PATH.",
        ],
    }


def test_worker_retry_preserves_runtime_warning_surfacing(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1workerwarnretry001")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage, utc_now
    from app.repositories.tasks import list_task_log_summaries, retry_task_from_stage
    from app.worker import run_worker_iteration
    import app.services.task_runner as task_runner

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "failed"
        session.add(task)

        stages = session.exec(select(TaskStage).where(TaskStage.task_id == task_id).order_by(TaskStage.id)).all()
        base_time = utc_now() - timedelta(hours=1)
        for index, stage in enumerate(stages, start=1):
            if stage.name in {"ingest", "media_prep", "asr"}:
                stage.status = "success"
                stage.attempts = 1
                stage.started_at = base_time + timedelta(minutes=index)
                stage.finished_at = stage.started_at + timedelta(seconds=5)
            elif stage.name == "translation":
                stage.status = "failed"
                stage.summary = "translation_failed"
                stage.attempts = 1
                stage.started_at = base_time + timedelta(minutes=index)
                stage.finished_at = stage.started_at + timedelta(seconds=5)
            else:
                stage.status = "pending"
                stage.attempts = 0
                stage.started_at = None
                stage.finished_at = None
            session.add(stage)

        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        job.status = "failed"
        job.stage_name = "translation"
        session.add(job)

    with session_scope() as session:
        retry_task_from_stage(session, task_id, "translation")

    called: list[str] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str) -> None:
            assert current_task_id == task_id
            called.append(stage_name)

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )
    monkeypatch.setattr("app.services.capability_checks.get_runtime_capabilities", _warning_payload)

    claimed = run_worker_iteration()

    assert claimed is not None
    assert claimed.task_id == task_id
    assert claimed.stage_name == "translation"
    assert called == ["translation", "highlight", "export", "report"]

    with session_scope() as session:
        log_summaries = list_task_log_summaries(session, task_id)
        stages = {
            stage.name: stage
            for stage in session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
        }
        translation_attempts = stages["translation"].attempts

    assert log_summaries is not None
    translation_summary = next(entry["summary"] for entry in log_summaries if entry["stage_name"] == "translation")
    assert _extract_runtime_summary(translation_summary) == {
        "accelerator": {
            "available": False,
            "backend": "cpu",
            "device_count": 0,
            "device_name": None,
            "torch_build_family": "cuda",
        },
        "detected_profile": "cpu-only",
        "issue_codes": ["wrong_torch_build_cuda_on_wsl"],
        "issues": [
            {
                "code": "wrong_torch_build_cuda_on_wsl",
                "message": "WSL host is using a CUDA-built torch wheel instead of the dedicated ROCm build.",
                "severity": "error",
            }
        ],
        "status": "error",
        "warnings": [
            "WSL detected a CUDA-built torch wheel. Install the dedicated WSL ROCm backend environment instead.",
            "GPU runtime was not detected; backend is operating in cpu-only mode.",
            "System tool 'ffprobe' was not found on PATH.",
        ],
    }
    assert translation_attempts == 2


def test_claim_next_job_recovers_stale_running_gpu_job(backend_env, monkeypatch) -> None:
    stale_task_id = _create_task("https://www.bilibili.com/video/BV1stale001")
    pending_task_id = _create_task("https://www.bilibili.com/video/BV1pending001")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage, utc_now
    from app.worker import claim_next_job

    stale_now = utc_now() - timedelta(minutes=10)
    monkeypatch.setenv("APP_WORKER_RUNNING_JOB_STALE_SECONDS", "60")

    with session_scope() as session:
        stale_task = session.get(Task, stale_task_id)
        assert stale_task is not None
        stale_task.status = "running"
        stale_task.updated_at = stale_now
        session.add(stale_task)

        stale_job = session.exec(select(TaskJob).where(TaskJob.task_id == stale_task_id)).one()
        stale_job.status = "running"
        stale_job.stage_name = "ingest"
        stale_job.started_at = stale_now
        stale_job.updated_at = stale_now
        stale_job.finished_at = None
        session.add(stale_job)

        stale_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == stale_task_id).where(TaskStage.name == "ingest")
        ).one()
        stale_stage.status = "running"
        stale_stage.started_at = stale_now
        stale_stage.updated_at = stale_now
        stale_stage.finished_at = None
        session.add(stale_stage)

    claimed = claim_next_job()

    assert claimed is not None
    assert claimed.task_id == pending_task_id
    assert claimed.stage_name == "ingest"

    with session_scope() as session:
        stale_task = session.get(Task, stale_task_id)
        stale_job = session.exec(select(TaskJob).where(TaskJob.task_id == stale_task_id)).one()
        stale_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == stale_task_id).where(TaskStage.name == "ingest")
        ).one()
        stale_task_status = stale_task.status if stale_task is not None else None
        stale_job_status = stale_job.status
        stale_stage_status = stale_stage.status
        stale_stage_summary = stale_stage.summary

    assert stale_task is not None
    assert stale_task_status == "failed"
    assert stale_job_status == "failed"
    assert stale_stage_status == "failed"
    assert stale_stage_summary == "Recovered stale running job"

    ingest_log = Path(backend_env["data_dir"]) / "tasks" / stale_task_id / "logs" / "ingest.log"
    assert "worker:recovered stale running job" in ingest_log.read_text(encoding="utf-8")


def test_claim_next_job_kills_stale_asr_process_group_before_unblocking_queue(backend_env, monkeypatch) -> None:
    stale_task_id = _create_task("https://www.bilibili.com/video/BV1staleasr001")
    pending_task_id = _create_task("https://www.bilibili.com/video/BV1pendingasr001")

    from app.db import session_scope
    from app.models import Task, TaskExecutionControl, TaskExecutionProgress, TaskJob, TaskStage, utc_now
    from app.worker import claim_next_job

    stale_now = utc_now() - timedelta(minutes=10)
    monkeypatch.setenv("APP_WORKER_RUNNING_JOB_STALE_SECONDS", "60")
    child = subprocess.Popen(["python", "-c", "import time; time.sleep(30)"], start_new_session=True)

    try:
        with session_scope() as session:
            stale_task = session.get(Task, stale_task_id)
            assert stale_task is not None
            stale_task.status = "running"
            stale_task.updated_at = stale_now
            session.add(stale_task)

            stale_job = session.exec(select(TaskJob).where(TaskJob.task_id == stale_task_id)).one()
            stale_job.status = "running"
            stale_job.stage_name = "asr"
            stale_job.started_at = stale_now
            stale_job.updated_at = stale_now
            stale_job.finished_at = None
            session.add(stale_job)

            stale_stage = session.exec(
                select(TaskStage).where(TaskStage.task_id == stale_task_id).where(TaskStage.name == "asr")
            ).one()
            stale_stage.status = "running"
            stale_stage.started_at = stale_now
            stale_stage.updated_at = stale_now
            stale_stage.finished_at = None
            session.add(stale_stage)

            session.add(
                TaskExecutionControl(
                    task_id=stale_task_id,
                    execution_token="token-stale-asr",
                    active_process_group_id=child.pid,
                    cancel_requested=False,
                    force_kill_requested=False,
                    heartbeat_at=stale_now,
                )
            )
            session.add(
                TaskExecutionProgress(
                    task_id=stale_task_id,
                    stage_name="asr",
                    current_phase="transcribe",
                    phase_index=3,
                    phase_count=5,
                    latest_message="stale progress",
                    phase_timings_json=json.dumps(
                        [
                            {"name": "model_load", "status": "success", "elapsed_ms": 250},
                            {"name": "vad", "status": "success", "elapsed_ms": 500},
                            {"name": "transcribe", "status": "running", "elapsed_ms": 750},
                            {"name": "align", "status": "pending", "elapsed_ms": None},
                            {"name": "persist", "status": "pending", "elapsed_ms": None},
                        ]
                    ),
                    heartbeat_at=stale_now,
                )
            )

        claimed = claim_next_job()

        assert claimed is not None
        assert claimed.task_id == pending_task_id
        assert claimed.stage_name == "ingest"

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and child.poll() is None:
            time.sleep(0.05)

        assert child.poll() is not None

        with session_scope() as session:
            stale_task = session.get(Task, stale_task_id)
            stale_job = session.exec(select(TaskJob).where(TaskJob.task_id == stale_task_id)).one()
            stale_stage = session.exec(
                select(TaskStage).where(TaskStage.task_id == stale_task_id).where(TaskStage.name == "asr")
            ).one()
            control = session.get(TaskExecutionControl, stale_task_id)
            execution_progress = session.get(TaskExecutionProgress, stale_task_id)
            stale_task_status = stale_task.status if stale_task is not None else None
            stale_job_status = stale_job.status
            stale_stage_status = stale_stage.status
            stale_stage_summary = stale_stage.summary
            assert control is not None
            execution_token = control.execution_token
            active_process_group_id = control.active_process_group_id

        assert stale_task is not None
        assert stale_task_status == "failed"
        assert stale_job_status == "failed"
        assert stale_stage_status == "failed"
        assert stale_stage_summary == "Recovered stale running job"
        assert execution_token is None
        assert active_process_group_id is None
        assert execution_progress is None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_claim_next_job_keeps_fresh_running_gpu_job_blocking_queue(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1fresh001")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage, utc_now
    from app.worker import claim_next_job

    fresh_now = utc_now()
    monkeypatch.setenv("APP_WORKER_RUNNING_JOB_STALE_SECONDS", "3600")

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "running"
        task.updated_at = fresh_now
        session.add(task)

        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        job.status = "running"
        job.stage_name = "ingest"
        job.started_at = fresh_now
        job.updated_at = fresh_now
        job.finished_at = None
        session.add(job)

        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        stage.status = "running"
        stage.started_at = fresh_now
        stage.updated_at = fresh_now
        stage.finished_at = None
        session.add(stage)

    claimed = claim_next_job()

    assert claimed is None


def test_worker_queue_claim_updates_legacy_job_and_finishes_queue_entry(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1queueworker001")

    from app.db import session_scope
    from app.models import PipelineRun, QueueEntry, TaskJob
    from app.worker import run_worker_iteration
    import app.services.task_runner as task_runner

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: lambda session, current_task_id: None for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )
    monkeypatch.setattr("app.services.capability_checks.get_runtime_capabilities", lambda: {"warnings": [], "issues": []})

    claimed = run_worker_iteration()

    assert claimed is not None
    assert claimed.task_id == task_id
    with session_scope() as session:
        queue_entry = session.get(QueueEntry, task_id)
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        run = session.exec(select(PipelineRun).where(PipelineRun.task_id == task_id)).one()
        queue_entry_state = queue_entry.state if queue_entry is not None else None
        job_status = job.status
        run_status = run.status

    assert queue_entry_state == "finished"
    assert job_status == "success"
    assert run_status == "success"
