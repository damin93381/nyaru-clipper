from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import select


def _reset_runtime_state() -> None:
    from app.db import reset_db_runtime

    reset_db_runtime()


@pytest.fixture()
def backend_env(tmp_path, monkeypatch) -> dict[str, Path | str]:
    data_dir = tmp_path / "data"
    database_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    _reset_runtime_state()
    return {"data_dir": data_dir, "database_path": database_path}


def _create_task(source_url: str) -> str:
    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, source_url)
    return payload["task_id"]


def test_run_task_pipeline_persists_completed_stage_after_token_bound_no_cancel(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runnercontrol004")

    from app.db import session_scope
    from app.models import TaskStage, WorkstationEvent
    from app.services.task_control import activate_execution
    import app.services.task_runner as task_runner

    # Given: an execution-token-bound runner with no cancellation request.
    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: lambda _session, _task_id: None for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )
    with session_scope() as session:
        activate_execution(session, task_id=task_id, execution_token="token-no-cancel")

    # When: the runner completes its stage checkpoints while checking control requests.
    with session_scope() as session:
        result = task_runner.run_task_pipeline(session, task_id, execution_token="token-no-cancel")

    # Then: the persisted stage and its durable projection agree on completion.
    with session_scope() as session:
        ingest_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        ingest_events = session.exec(
            select(WorkstationEvent)
            .where(WorkstationEvent.entity_id == task_id)
            .where(WorkstationEvent.event_type == "stage.updated")
            .order_by(WorkstationEvent.id)
        ).all()
        ingest_status = ingest_stage.status
        event_payloads = [json.loads(event.payload_json) for event in ingest_events]

    assert result.final_status == "success"
    assert ingest_status == "success"
    assert {
        "task_id": task_id,
        "stage_name": "ingest",
        "status": "success",
        "failure_code": None,
        "attempts": 1,
    } in event_payloads


def test_control_read_preserves_dirty_runner_stage_checkpoint_when_no_cancel(backend_env) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runnercontrol006")

    from app.db import session_scope
    from app.models import TaskStage
    from app.services.task_control import get_control_requests

    # Given: a runner has completed a stage but has not committed its checkpoint yet.
    with session_scope() as session:
        ingest_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        ingest_stage.status = "success"
        session.add(ingest_stage)

        # When: the runner reads a no-cancellation control request before checkpointing.
        requests = get_control_requests(session, task_id=task_id)
        ingest_status = ingest_stage.status

    # Then: the control read cannot discard the completed stage state.
    assert requests.cancel_requested is False
    assert requests.force_kill_requested is False
    assert ingest_status == "success"


def test_process_control_poll_preserves_dirty_runner_stage_checkpoint_when_no_cancel(backend_env) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runnercontrol007")

    from app.db import session_scope
    from app.models import TaskStage
    from app.services.pipeline_support import _load_control_requests

    # Given: a tracked-process poll occurs after the runner has completed a stage checkpoint.
    with session_scope() as session:
        ingest_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        ingest_stage.status = "success"
        session.add(ingest_stage)

        # When: the process-control poll reads a no-cancellation request.
        cancel_requested, force_kill_requested = _load_control_requests(session, task_id=task_id)
        ingest_status = ingest_stage.status

    # Then: reading control state cannot expire the caller's dirty stage checkpoint.
    assert cancel_requested is False
    assert force_kill_requested is False
    assert ingest_status == "success"


def test_has_tracked_process_group_preserves_dirty_runner_stage_checkpoint(backend_env) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runnercontrol008")

    from app.db import session_scope
    from app.models import TaskStage
    from app.services.task_control import has_tracked_process_group

    # Given: a runner has a dirty stage checkpoint and no tracked process group.
    with session_scope() as session:
        ingest_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        ingest_stage.status = "success"
        session.add(ingest_stage)

        # When: force-kill eligibility checks the execution-control record.
        tracked = has_tracked_process_group(session, task_id=task_id)
        ingest_status = ingest_stage.status

    # Then: the read leaves the caller's uncommitted runner state intact.
    assert tracked is False
    assert ingest_status == "success"


def test_best_effort_kill_preserves_dirty_runner_stage_and_signals_group(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runnercontrol009")
    process_group_id = 4321

    from app.db import session_scope
    from app.models import TaskExecutionControl, TaskStage
    from app.services.task_control import activate_execution, best_effort_kill_active_process_group

    # Given: a persisted active process group and a separate dirty runner checkpoint.
    with session_scope() as session:
        activate_execution(session, task_id=task_id, execution_token="token-active-process-group")
        control = session.get(TaskExecutionControl, task_id)
        assert control is not None
        control.active_process_group_id = process_group_id
        session.add(control)

    signalled_process_groups: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.services.task_control.os.killpg",
        lambda received_process_group_id, signal_number: signalled_process_groups.append(
            (received_process_group_id, signal_number)
        ),
    )
    with session_scope() as session:
        ingest_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        ingest_stage.status = "success"
        session.add(ingest_stage)

        # When: stale-job recovery kills the tracked process group.
        terminated_process_group_id = best_effort_kill_active_process_group(session, task_id=task_id)
        ingest_status = ingest_stage.status

    # Then: the group is still signalled and the caller's checkpoint is not expired.
    assert terminated_process_group_id == process_group_id
    assert signalled_process_groups == [(process_group_id, 9)]
    assert ingest_status == "success"
