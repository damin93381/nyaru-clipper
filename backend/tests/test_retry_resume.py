from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlmodel import select


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def _create_task(data_dir: Path, db_path: Path) -> str:
    import os

    os.environ["APP_DATA_DIR"] = str(data_dir)
    os.environ["APP_DATABASE_URL"] = f"sqlite:///{db_path}"
    _reset_runtime_state()

    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, "https://www.bilibili.com/video/BV1resume001")
        return payload["task_id"]


def test_resume_from_translation_failure_reruns_only_failed_stage_and_downstream(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "task-state.sqlite3"
    task_id = _create_task(data_dir, db_path)

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage, utc_now
    from app.repositories.tasks import retry_task_from_stage
    import app.services.task_runner as task_runner
    from app.worker import run_worker_iteration

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
            called.append(stage_name)

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    claimed = run_worker_iteration()

    assert claimed is not None
    assert claimed.task_id == task_id
    assert called == ["translation", "highlight", "export", "report"]

    with session_scope() as session:
        stages = {
            stage.name: stage
            for stage in session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
        }
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        stage_statuses = {name: stage.status for name, stage in stages.items()}
        stage_attempts = {name: stage.attempts for name, stage in stages.items()}
        job_status = job.status

    assert stage_statuses["ingest"] == "success"
    assert stage_statuses["media_prep"] == "success"
    assert stage_statuses["asr"] == "success"
    assert stage_attempts["translation"] == 2
    assert stage_attempts["highlight"] == 1
    assert stage_attempts["export"] == 1
    assert stage_attempts["report"] == 1
    assert job_status == "success"
