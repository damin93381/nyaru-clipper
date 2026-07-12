from __future__ import annotations

import pytest
from sqlmodel import Session, select


def _reset_runtime_state() -> None:
    from app.db import reset_db_runtime

    reset_db_runtime()


@pytest.fixture()
def database(tmp_path, monkeypatch):
    database_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    _reset_runtime_state()

    from app.db import get_engine, init_db

    init_db()
    return get_engine()


def _create_task(session: Session, task_id: str) -> None:
    from app.models import CANONICAL_STAGES, Task, TaskJob, TaskStage

    session.add(
        Task(
            id=task_id,
            source_url=f"file:///fixtures/{task_id}.mp4",
            normalized_source_url=f"file:///fixtures/{task_id}.mp4",
        )
    )
    session.add(TaskJob(task_id=task_id, stage_name="ingest", status="pending"))
    session.add_all([TaskStage(task_id=task_id, name=name, status="pending") for name in CANONICAL_STAGES])
    session.commit()


def test_pending_pipeline_run_is_reused_and_every_legacy_stage_is_mirrored(database, monkeypatch) -> None:
    from app.services.workstation_runs import create_pipeline_run, get_pending_pipeline_run
    import app.services.task_runner as task_runner

    with Session(database) as session:
        _create_task(session, "task-success")
        pending_run = create_pipeline_run(session, "task-success", "queue")
        pending_run_id = pending_run.id
        session.commit()

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: lambda session, task_id: None for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    with Session(database) as session:
        result = task_runner.run_task_pipeline(session, "task-success")
        pending_after_start = get_pending_pipeline_run(session, "task-success")
        session.commit()

    from app.models import CANONICAL_STAGES, PipelineRun, StageRun

    with Session(database) as session:
        run = session.get(PipelineRun, pending_run_id)
        stage_runs = session.exec(select(StageRun).where(StageRun.run_id == pending_run_id).order_by(StageRun.id)).all()

    assert result.final_status == "success"
    assert pending_after_start is None
    assert run is not None
    assert run.status == "success"
    assert [stage.name for stage in stage_runs] == CANONICAL_STAGES
    assert [stage.status for stage in stage_runs] == ["success"] * len(CANONICAL_STAGES)


def test_failure_cancellation_and_retry_preserve_accurate_run_history(database, monkeypatch) -> None:
    from app.models import PipelineRun, TaskStage
    from app.repositories.tasks import retry_task_from_stage
    from app.services.workstation_runs import create_pipeline_run
    import app.services.task_runner as task_runner

    with Session(database) as session:
        _create_task(session, "task-history")
        failed_run = create_pipeline_run(session, "task-history", "queue")
        failed_run_id = failed_run.id
        session.commit()

    def executor_for(stage_name: str):
        def execute(session, task_id: str) -> None:
            if stage_name == "translation":
                raise RuntimeError("translation exploded")

        return execute

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: executor_for(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )
    with pytest.raises(RuntimeError, match="translation exploded"):
        with Session(database) as session:
            task_runner.run_task_pipeline(session, "task-history")
            session.commit()

    with Session(database) as session:
        retry_task_from_stage(session, "task-history", "translation")
        session.commit()
        runs = session.exec(select(PipelineRun).where(PipelineRun.task_id == "task-history").order_by(PipelineRun.created_at)).all()
        translation = session.exec(
            select(TaskStage).where(TaskStage.task_id == "task-history").where(TaskStage.name == "translation")
        ).one()
        from app.repositories.workstation import get_workstation_task_overview

        overview = get_workstation_task_overview(session, "task-history")

    assert len(runs) == 2
    assert runs[0].id == failed_run_id
    assert runs[0].status == "failed"
    assert runs[1].status == "pending"
    assert runs[1].trigger == "retry"
    assert translation.status == "pending"
    assert overview is not None
    assert overview.pipeline_run_id == runs[1].id
    overview_statuses = {stage.name: stage.status for stage in overview.stages}
    assert overview_statuses["translation"] == "pending"
    assert "failed" not in overview_statuses.values()

    from app.services.workstation_queue import QueueConflict

    with Session(database) as session:
        with pytest.raises(QueueConflict, match="terminal"):
            retry_task_from_stage(session, "task-history", "translation")
        run_count = len(session.exec(select(PipelineRun).where(PipelineRun.task_id == "task-history")).all())

    assert run_count == 2


def test_retry_rechecks_task_terminality_after_acquiring_the_queue_lock(database, monkeypatch) -> None:
    from app.models import PipelineRun, QueueState, Task, TaskStage
    from app.repositories.tasks import retry_task_from_stage
    from app.services.workstation_queue import QueueConflict
    import app.services.workstation_queue as workstation_queue

    with Session(database) as session:
        _create_task(session, "task-retry-race")
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == "task-retry-race").where(TaskStage.name == "ingest")
        ).one()
        stage.status = "failed"
        session.add(stage)
        session.commit()

    original_begin_queue_mutation = workstation_queue.begin_queue_mutation
    losing_session: Session | None = None

    def interleave_winning_retry_before_losing_lock(session: Session) -> None:
        if session is losing_session:
            session.rollback()
            with Session(database) as winning_session:
                result = retry_task_from_stage(winning_session, "task-retry-race", "ingest")
                assert result is not None
                winning_session.commit()
        original_begin_queue_mutation(session)

    monkeypatch.setattr(workstation_queue, "begin_queue_mutation", interleave_winning_retry_before_losing_lock)

    with Session(database) as session:
        losing_session = session
        with pytest.raises(QueueConflict, match="terminal"):
            retry_task_from_stage(session, "task-retry-race", "ingest")
        session.rollback()

    with Session(database) as session:
        runs = session.exec(select(PipelineRun).where(PipelineRun.task_id == "task-retry-race")).all()
        queue_state = session.get(QueueState, 1)
        task = session.get(Task, "task-retry-race")

    assert len(runs) == 1
    assert queue_state is not None
    assert queue_state.revision == 2
    assert task is not None
    assert task.status == "pending"


def test_cancellation_finalizes_the_pending_run_without_erasing_stage_history(database, monkeypatch) -> None:
    from app.models import PipelineRun, StageRun
    from app.services.task_control import activate_execution, request_cancel
    from app.services.workstation_runs import create_pipeline_run
    import app.services.task_runner as task_runner

    with Session(database) as session:
        _create_task(session, "task-cancelled")
        run = create_pipeline_run(session, "task-cancelled", "queue")
        run_id = run.id
        session.commit()

    def executor_for(stage_name: str):
        def execute(session, task_id: str) -> None:
            if stage_name == "ingest":
                request_cancel(session, task_id=task_id)

        return execute

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: executor_for(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    with Session(database) as session:
        activate_execution(session, task_id="task-cancelled", execution_token="exec-cancelled")
        result = task_runner.run_task_pipeline(session, "task-cancelled", execution_token="exec-cancelled")
        session.commit()

    with Session(database) as session:
        cancelled_run = session.get(PipelineRun, run_id)
        stage_runs = session.exec(select(StageRun).where(StageRun.run_id == run_id)).all()

    assert result.final_status == "cancelled"
    assert cancelled_run is not None
    assert cancelled_run.status == "cancelled"
    assert [(stage.name, stage.status) for stage in stage_runs] == [("ingest", "success")]
