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


def test_duplicate_submission_returns_existing_task_after_source_video_id_is_discovered(backend_env) -> None:
    task_id = _create_task("https://www.bilibili.com/bangumi/play/ep424242")

    from app.db import session_scope
    from app.models import Task, TaskJob
    from app.repositories.tasks import create_task

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.source_video_id = "BV1dedupe123"
        session.add(task)

    with session_scope() as session:
        payload, created = create_task(session, "https://www.bilibili.com/video/BV1dedupe123?p=9")
        task_count = len(session.exec(select(Task)).all())
        job_count = len(session.exec(select(TaskJob)).all())

    assert created is False
    assert payload["task_id"] == task_id
    assert payload["created"] is False
    assert task_count == 1
    assert job_count == 1


def test_run_task_pipeline_executes_canonical_stage_order_and_checkpoints_each_success(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runner001")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage
    import app.services.task_runner as task_runner

    called: list[str] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str) -> None:
            assert current_task_id == task_id
            called.append(stage_name)
            if stage_name == "ingest":
                task = session.get(Task, current_task_id)
                assert task is not None
                task.source_video_id = "BV1runner001"
                session.add(task)

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    with session_scope() as session:
        result = task_runner.run_task_pipeline(session, task_id)

    assert result.final_status == "success"
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
        stage_started = [stage.started_at for stage in stages]
        stage_finished = [stage.finished_at for stage in stages]

    assert task_status == "success"
    assert task_source_video_id == "BV1runner001"
    assert job_status == "success"
    assert job_stage_name == "report"
    assert stage_names == list(task_runner.CANONICAL_STAGE_ORDER)
    assert stage_statuses == ["success"] * len(task_runner.CANONICAL_STAGE_ORDER)
    assert stage_attempts == [1] * len(task_runner.CANONICAL_STAGE_ORDER)
    assert all(value is not None for value in stage_started)
    assert all(value is not None for value in stage_finished)


def test_run_task_pipeline_keeps_upstream_success_and_failure_summary(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runner002")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage
    from app.repositories.tasks import list_task_log_summaries
    import app.services.task_runner as task_runner

    called: list[str] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str) -> None:
            called.append(stage_name)
            if stage_name == "translation":
                raise RuntimeError("translation exploded")

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    with pytest.raises(RuntimeError, match="translation exploded"):
        with session_scope() as session:
            task_runner.run_task_pipeline(session, task_id)

    assert called == ["ingest", "media_prep", "asr", "translation"]

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        stages = {
            stage.name: stage
            for stage in session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
        }
        log_summaries = list_task_log_summaries(session, task_id)
        task_status = task.status
        job_status = job.status
        job_stage_name = job.stage_name
        stage_statuses = {name: stage.status for name, stage in stages.items()}
        translation_summary = stages["translation"].summary

    assert task_status == "failed"
    assert job_status == "failed"
    assert job_stage_name == "translation"
    assert stage_statuses["ingest"] == "success"
    assert stage_statuses["media_prep"] == "success"
    assert stage_statuses["asr"] == "success"
    assert stage_statuses["translation"] == "failed"
    assert translation_summary == "translation exploded"
    assert stage_statuses["highlight"] == "pending"
    assert stage_statuses["export"] == "pending"
    assert stage_statuses["report"] == "pending"
    assert any(
        entry["stage_name"] == "translation" and "translation exploded" in (entry["summary"] or "")
        for entry in log_summaries
    )
