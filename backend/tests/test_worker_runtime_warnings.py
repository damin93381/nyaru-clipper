from __future__ import annotations

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
        "status": "warning",
        "detected_profile": "cpu-only",
        "platform": {
            "is_wsl": False,
            "machine": "x86_64",
            "release": "6.8.0-generic",
            "system": "linux",
            "version": "#1 SMP PREEMPT_DYNAMIC",
        },
        "accelerator": {
            "available": False,
            "backend": "cpu",
            "cuda_version": None,
            "device_count": 0,
            "hip_version": None,
            "kind": "cpu",
            "torch_available": True,
            "torch_version": "2.6.0",
        },
        "dependencies": {"tools": {}, "python": {}},
        "warnings": [
            "GPU runtime was not detected; backend is operating in cpu-only mode.",
            "System tool 'ffprobe' was not found on PATH.",
        ],
    }


def _expected_warning_summary() -> str:
    return (
        'worker_preflight_warning={"detected_profile": "cpu-only", '
        '"status": "warning", '
        '"warnings": ["GPU runtime was not detected; backend is operating in cpu-only mode.", '
        '"System tool \'ffprobe\' was not found on PATH."]}'
    )


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
    assert any(
        entry["stage_name"] == "ingest" and entry["summary"] == _expected_warning_summary()
        for entry in log_summaries
    )


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
    assert any(
        entry["stage_name"] == "translation" and entry["summary"] == _expected_warning_summary()
        for entry in log_summaries
    )
    assert translation_attempts == 2
