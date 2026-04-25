from __future__ import annotations

import subprocess
from pathlib import Path

from sqlmodel import Session, select

from app.models import Task, TaskStage, utc_now


def append_stage_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def run_logged_command(args: list[str], *, log_path: Path) -> subprocess.CompletedProcess[str]:
    append_stage_log(log_path, f"$ {' '.join(args)}")
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.stdout:
        append_stage_log(log_path, result.stdout.rstrip())
    if result.stderr:
        append_stage_log(log_path, result.stderr.rstrip())
    append_stage_log(log_path, f"exit_code={result.returncode}")
    return result


def set_stage_status(session: Session, *, task_id: str, stage_name: str, status: str, summary: str) -> None:
    stage = session.exec(
        select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == stage_name)
    ).first()
    if stage is None:
        raise ValueError(f"Stage {stage_name!r} not found for task {task_id!r}")

    now = utc_now()
    stage.status = status
    stage.summary = summary
    stage.updated_at = now
    if status == "success":
        stage.finished_at = now
    elif status == "failed":
        stage.finished_at = now
        task = session.get(Task, task_id)
        if task is not None:
            task.status = "failed"
            task.updated_at = now
            session.add(task)
    session.add(stage)
