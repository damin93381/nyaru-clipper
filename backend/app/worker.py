from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from sqlmodel import select

from app.db import session_scope
from app.models import Task, TaskJob, TaskStage, utc_now
from app.services import capability_checks
from app.services.pipeline_support import append_stage_log
from app.services.storage import log_file_for_stage
from app.services.task_runner import run_task_pipeline


@dataclass(slots=True)
class ClaimedJob:
    task_id: str
    stage_name: str


def _build_preflight_warning_summary(capabilities: dict[str, object]) -> str | None:
    warnings = capabilities.get("warnings")
    if not isinstance(warnings, list) or not warnings:
        return None

    summary_payload = {
        "detected_profile": capabilities.get("detected_profile"),
        "status": capabilities.get("status"),
        "warnings": warnings,
    }
    return f"worker_preflight_warning={json.dumps(summary_payload, ensure_ascii=False, sort_keys=True)}"


def _surface_preflight_warning(task_id: str, stage_name: str) -> str | None:
    summary = _build_preflight_warning_summary(capability_checks.get_runtime_capabilities())
    if summary is None:
        return None

    append_stage_log(log_file_for_stage(task_id, stage_name), summary)
    return summary


def claim_next_job() -> ClaimedJob | None:
    with session_scope() as session:
        running_gpu_job = session.exec(
            select(TaskJob).where(TaskJob.gpu_bound.is_(True)).where(TaskJob.status == "running")
        ).first()
        if running_gpu_job is not None:
            return None

        job = session.exec(
            select(TaskJob).where(TaskJob.status == "pending").order_by(TaskJob.created_at)
        ).first()
        if job is None:
            return None

        task = session.get(Task, job.task_id)
        stage = session.exec(
            select(TaskStage)
            .where(TaskStage.task_id == job.task_id)
            .where(TaskStage.name == job.stage_name)
        ).first()
        if task is None or stage is None:
            return None

        now = utc_now()
        job.status = "running"
        job.started_at = now
        job.updated_at = now
        task.status = "running"
        task.updated_at = now
        stage.status = "running"
        stage.started_at = now
        stage.attempts += 1
        stage.updated_at = now
        session.add(job)
        session.add(task)
        session.add(stage)
        return ClaimedJob(task_id=job.task_id, stage_name=job.stage_name)


def complete_job(task_id: str, *, success: bool) -> None:
    with session_scope() as session:
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
        task = session.get(Task, task_id)
        if job is None or task is None:
            return
        stage = session.exec(
            select(TaskStage)
            .where(TaskStage.task_id == task_id)
            .where(TaskStage.name == job.stage_name)
        ).first()
        now = utc_now()
        job.status = "success" if success else "failed"
        job.finished_at = now
        job.updated_at = now
        task.status = "success" if success else "failed"
        task.updated_at = now
        session.add(job)
        session.add(task)

        if stage is not None:
            stage.status = "success" if success else "failed"
            stage.finished_at = now
            stage.summary = "Completed by worker" if success else "Worker execution failed"
            stage.updated_at = now
            session.add(stage)


def run_worker_iteration(processor: Callable[[ClaimedJob], bool] | None = None) -> ClaimedJob | None:
    claimed_job = claim_next_job()
    if claimed_job is None:
        return None
    if processor is None:
        preflight_warning = _surface_preflight_warning(claimed_job.task_id, claimed_job.stage_name)
        with session_scope() as session:
            try:
                run_task_pipeline(
                    session,
                    claimed_job.task_id,
                    start_stage_name=claimed_job.stage_name,
                    claimed_stage_running=True,
                )
            finally:
                if preflight_warning is not None:
                    append_stage_log(log_file_for_stage(claimed_job.task_id, claimed_job.stage_name), preflight_warning)
    else:
        success = processor(claimed_job)
        complete_job(claimed_job.task_id, success=success)
    return claimed_job


def worker_loop(poll_interval: float = 1.0, processor: Callable[[ClaimedJob], bool] | None = None) -> None:
    while True:
        claimed_job = run_worker_iteration(processor=processor)
        if claimed_job is None:
            time.sleep(poll_interval)
            continue
