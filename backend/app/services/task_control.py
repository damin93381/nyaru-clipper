from __future__ import annotations

from dataclasses import dataclass
import os
import signal
from typing import Any

from sqlmodel import Session, SQLModel, select

from app.db import get_engine
from app.models import Task, TaskExecutionControl, TaskJob, TaskStage, utc_now
from app.services.workstation_events import publish_stage_updated, publish_task_updated

PIPELINE_EXECUTION_CONTEXT_KEY = "pipeline_execution_context"


class StaleExecutionTokenError(RuntimeError):
    def __init__(
        self,
        *,
        task_id: str,
        execution_token: str | None,
        current_execution_token: str | None,
    ):
        self.task_id = task_id
        self.execution_token = execution_token
        self.current_execution_token = current_execution_token
        super().__init__(
            f"Execution token for task {task_id!r} is stale: "
            f"{execution_token!r} != {current_execution_token!r}"
        )


@dataclass(slots=True)
class TaskControlRequests:
    cancel_requested: bool
    force_kill_requested: bool


def _ensure_control_table() -> None:
    SQLModel.metadata.create_all(get_engine(), tables=[TaskExecutionControl.__table__])


def bind_execution_context(session: Session, *, task_id: str, execution_token: str) -> None:
    session.info[PIPELINE_EXECUTION_CONTEXT_KEY] = {
        "task_id": task_id,
        "execution_token": execution_token,
    }


def clear_execution_context(session: Session) -> None:
    session.info.pop(PIPELINE_EXECUTION_CONTEXT_KEY, None)


def get_execution_context(session: Session) -> dict[str, Any] | None:
    context = session.info.get(PIPELINE_EXECUTION_CONTEXT_KEY)
    return context if isinstance(context, dict) else None


def activate_execution(
    session: Session,
    *,
    task_id: str,
    execution_token: str,
    heartbeat_at=None,
) -> TaskExecutionControl:
    _ensure_control_table()
    control = session.get(TaskExecutionControl, task_id)
    if control is None:
        control = TaskExecutionControl(task_id=task_id)
    now = utc_now()
    control.execution_token = execution_token
    control.active_process_group_id = None
    control.cancel_requested = False
    control.force_kill_requested = False
    control.heartbeat_at = heartbeat_at or now
    control.updated_at = now
    session.add(control)
    session.commit()
    session.refresh(control)
    return control


def ensure_current_execution_context(session: Session, *, task_id: str) -> None:
    context = get_execution_context(session)
    if context is None or context.get("task_id") != task_id:
        raise RuntimeError(f"No execution context bound for task {task_id!r}")
    _ensure_control_table()
    control = session.get(TaskExecutionControl, task_id)
    current_execution_token = control.execution_token if control is not None else None
    execution_token = context.get("execution_token")
    if execution_token != current_execution_token:
        raise StaleExecutionTokenError(
            task_id=task_id,
            execution_token=execution_token if isinstance(execution_token, str) else None,
            current_execution_token=current_execution_token,
        )


def request_cancel(session: Session, *, task_id: str) -> None:
    _ensure_control_table()
    control = session.get(TaskExecutionControl, task_id)
    if control is None or not is_actively_cancellable(session, task_id=task_id):
        raise ValueError(f"Task execution control missing for task {task_id!r}")
    control.cancel_requested = True
    control.updated_at = utc_now()
    session.add(control)
    session.commit()


def is_actively_cancellable(session: Session, *, task_id: str) -> bool:
    task = session.get(Task, task_id)
    if task is None or task.status != "running":
        return False
    job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
    if job is None or job.status != "running":
        return False
    stage = session.exec(
        select(TaskStage)
        .where(TaskStage.task_id == task_id)
        .where(TaskStage.name == job.stage_name)
    ).first()
    return stage is not None and stage.status == "running"


def request_force_kill(session: Session, *, task_id: str) -> None:
    _ensure_control_table()
    control = session.get(TaskExecutionControl, task_id)
    if control is None:
        raise ValueError(f"Task execution control missing for task {task_id!r}")
    control.force_kill_requested = True
    control.updated_at = utc_now()
    session.add(control)
    session.commit()


def has_tracked_process_group(session: Session, *, task_id: str) -> bool:
    _ensure_control_table()
    with Session(get_engine()) as control_session:
        control = control_session.get(TaskExecutionControl, task_id)
    return control is not None and control.active_process_group_id is not None


def can_force_kill(session: Session, *, task_id: str) -> bool:
    if not has_tracked_process_group(session, task_id=task_id):
        return False
    job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
    if job is None:
        return False
    if job.stage_name != "asr" or job.status != "running":
        return False
    stage = session.exec(
        select(TaskStage)
        .where(TaskStage.task_id == task_id)
        .where(TaskStage.name == "asr")
    ).first()
    return stage is not None and stage.status == "running"


def best_effort_kill_active_process_group(
    session: Session,
    *,
    task_id: str,
    signal_number: int = signal.SIGKILL,
) -> int | None:
    _ensure_control_table()
    with Session(get_engine()) as control_session:
        control = control_session.get(TaskExecutionControl, task_id)
    if control is None or control.active_process_group_id is None:
        return None
    process_group_id = int(control.active_process_group_id)
    try:
        os.killpg(process_group_id, signal_number)
    except ProcessLookupError:
        pass
    return process_group_id


def clear_execution_control(session: Session, *, task_id: str) -> None:
    _ensure_control_table()
    control = session.get(TaskExecutionControl, task_id)
    if control is None:
        return
    now = utc_now()
    control.execution_token = None
    control.active_process_group_id = None
    control.cancel_requested = False
    control.force_kill_requested = False
    control.heartbeat_at = None
    control.updated_at = now
    session.add(control)


def get_control_requests(session: Session, *, task_id: str) -> TaskControlRequests:
    _ensure_control_table()
    with Session(get_engine()) as control_session:
        control = control_session.get(TaskExecutionControl, task_id)
    if control is None:
        return TaskControlRequests(cancel_requested=False, force_kill_requested=False)
    return TaskControlRequests(
        cancel_requested=bool(control.cancel_requested),
        force_kill_requested=bool(control.force_kill_requested),
    )


def finalize_cancelled(session: Session, *, task_id: str, execution_token: str) -> None:
    ensure_current_execution_context(session, task_id=task_id)
    control = session.get(TaskExecutionControl, task_id)
    if control is None:
        raise ValueError(f"Task execution control missing for task {task_id!r}")

    now = utc_now()
    task = session.get(Task, task_id)
    job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
    stage = None
    if job is not None:
        stage = session.exec(
            select(TaskStage)
            .where(TaskStage.task_id == task_id)
            .where(TaskStage.name == job.stage_name)
        ).first()

    if task is not None:
        task.status = "cancelled"
        task.updated_at = now
        session.add(task)
        publish_task_updated(session, task)

    if job is not None:
        job.status = "cancelled"
        job.finished_at = now
        job.updated_at = now
        session.add(job)

    if stage is not None and stage.status == "running":
        stage.status = "cancelled"
        stage.summary = stage.summary or "Cancelled"
        stage.finished_at = now
        stage.updated_at = now
        session.add(stage)
        publish_stage_updated(session, stage)

    control.execution_token = None
    control.active_process_group_id = None
    control.cancel_requested = False
    control.force_kill_requested = False
    control.heartbeat_at = None
    control.updated_at = now
    session.add(control)


def finalize_execution(session: Session, *, task_id: str, execution_token: str) -> None:
    ensure_current_execution_context(session, task_id=task_id)
    control = session.get(TaskExecutionControl, task_id)
    if control is None:
        raise ValueError(f"Task execution control missing for task {task_id!r}")

    now = utc_now()
    control.execution_token = None
    control.active_process_group_id = None
    control.cancel_requested = False
    control.force_kill_requested = False
    control.heartbeat_at = None
    control.updated_at = now
    session.add(control)
