from __future__ import annotations

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


def test_worker_iteration_runs_the_canonical_pipeline_smoke_path(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/bangumi/play/ep424242")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage
    import app.services.task_runner as task_runner
    from app.worker import run_worker_iteration

    called: list[str] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str):
            assert current_task_id == task_id
            called.append(stage_name)
            if stage_name == "ingest":
                task = session.get(Task, current_task_id)
                assert task is not None
                task.source_video_id = "BV1smoke001"
                session.add(task)
            if stage_name == "export":
                return task_runner.StageDirective(
                    status="skipped",
                    summary="Awaiting user-confirmed clip export",
                )

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    claimed = run_worker_iteration()

    assert claimed is not None
    assert claimed.task_id == task_id
    assert claimed.stage_name == "ingest"
    assert called == list(task_runner.CANONICAL_STAGE_ORDER)

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        stages = session.exec(select(TaskStage).where(TaskStage.task_id == task_id).order_by(TaskStage.id)).all()
        task_status = task.status
        task_source_video_id = task.source_video_id
        job_status = job.status
        job_stage_name = job.stage_name
        stage_names = [stage.name for stage in stages]
        stage_statuses = [stage.status for stage in stages]
        stage_attempts = [stage.attempts for stage in stages]
        stage_summaries = [stage.summary for stage in stages]

    assert task_status == "success"
    assert task_source_video_id == "BV1smoke001"
    assert job_status == "success"
    assert job_stage_name == "report"
    assert stage_names == list(task_runner.CANONICAL_STAGE_ORDER)
    assert stage_statuses == ["success", "success", "success", "success", "success", "skipped", "success"]
    assert stage_attempts == [1, 1, 1, 1, 1, 1, 1]
    assert stage_summaries[5] == "Awaiting user-confirmed clip export"
