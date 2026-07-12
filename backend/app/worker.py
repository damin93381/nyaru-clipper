from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable
from uuid import uuid4

from sqlmodel import select

from app.db import session_scope
from app.models import Task, TaskJob, TaskStage, utc_now
from app.repositories.tasks import clear_task_execution_progress
from app.services import capability_checks
from app.services.pipeline_support import append_stage_log
from app.services.storage import log_file_for_stage
from app.services.task_control import (
    activate_execution,
    best_effort_kill_active_process_group,
    clear_execution_control,
)
from app.services.task_runner import run_task_pipeline
from app.services.workstation_events import publish_stage_updated, publish_task_updated
from app.services.workstation_queue import begin_queue_mutation, claim_next_queue_entry, finish_queue_entry
from app.services.workstation_runs import finish_pipeline_run, get_active_pipeline_run, get_pending_pipeline_run, start_pipeline_run, sync_stage_run


@dataclass(slots=True)
class ClaimedJob:
    task_id: str
    stage_name: str


def _build_preflight_runtime_summary(capabilities: dict[str, object]) -> str | None:
    warnings = capabilities.get("warnings")
    issues = capabilities.get("issues")
    has_warnings = isinstance(warnings, list) and bool(warnings)
    has_issues = isinstance(issues, list) and bool(issues)
    if not has_warnings and not has_issues:
        return None

    issue_codes = [issue.get("code") for issue in issues if isinstance(issue, dict) and issue.get("code")] if isinstance(issues, list) else []
    accelerator_payload = capabilities.get("accelerator")
    accelerator_summary = {
        "available": accelerator_payload.get("available"),
        "backend": accelerator_payload.get("backend"),
        "device_count": accelerator_payload.get("device_count"),
        "device_name": accelerator_payload.get("device_name"),
        "torch_build_family": accelerator_payload.get("torch_build_family"),
    } if isinstance(accelerator_payload, dict) else {
        "available": None,
        "backend": None,
        "device_count": None,
        "device_name": None,
        "torch_build_family": None,
    }
    summary_payload = {
        "detected_profile": capabilities.get("detected_profile"),
        "status": capabilities.get("status"),
        "accelerator": accelerator_summary,
        "issues": issues if isinstance(issues, list) else [],
        "issue_codes": issue_codes,
        "warnings": warnings,
    }
    return f"worker_preflight_runtime={json.dumps(summary_payload, ensure_ascii=False, sort_keys=True)}"


def _surface_preflight_runtime_summary(task_id: str, stage_name: str) -> str | None:
    summary = _build_preflight_runtime_summary(capability_checks.get_runtime_capabilities())
    if summary is None:
        return None

    append_stage_log(log_file_for_stage(task_id, stage_name), summary)
    return summary


def _get_running_job_stale_seconds() -> int:
    raw_value = os.getenv("APP_WORKER_RUNNING_JOB_STALE_SECONDS", "300")
    try:
        return max(1, int(raw_value))
    except ValueError:
        return 300


def _normalize_comparable_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


def _mark_job_stale_failed(session, job: TaskJob) -> None:
    now = utc_now()
    task = session.get(Task, job.task_id)
    stage = session.exec(
        select(TaskStage)
        .where(TaskStage.task_id == job.task_id)
        .where(TaskStage.name == job.stage_name)
        ).first()

    job.status = "failed"
    job.finished_at = now
    job.updated_at = now
    session.add(job)
    active_run = get_active_pipeline_run(session, job.task_id)

    if task is not None:
        task.status = "failed"
        task.updated_at = now
        session.add(task)
        publish_task_updated(session, task)

    if stage is not None:
        stage.status = "failed"
        stage.summary = "Recovered stale running job"
        stage.failure_code = "stale_job_recovered"
        stage.finished_at = now
        stage.updated_at = now
        session.add(stage)
        publish_stage_updated(session, stage)
        append_stage_log(log_file_for_stage(job.task_id, job.stage_name), "worker:recovered stale running job")
        if active_run is not None:
            start_pipeline_run(session, active_run)
            sync_stage_run(session, active_run.id, stage)
    if active_run is not None:
        finish_pipeline_run(session, active_run, "failed")
    finish_queue_entry(session, job.task_id)


def _recover_stale_running_jobs(session) -> None:
    stale_before = _normalize_comparable_datetime(utc_now() - timedelta(seconds=_get_running_job_stale_seconds()))
    running_jobs = session.exec(
        select(TaskJob).where(TaskJob.gpu_bound.is_(True)).where(TaskJob.status == "running")
    ).all()
    for job in running_jobs:
        job_updated_at = _normalize_comparable_datetime(job.updated_at)
        if job_updated_at is None or job_updated_at > stale_before:
            continue
        if job.stage_name == "asr":
            terminated_process_group_id = best_effort_kill_active_process_group(session, task_id=job.task_id)
            if terminated_process_group_id is not None:
                append_stage_log(
                    log_file_for_stage(job.task_id, job.stage_name),
                    f"worker:terminated stale asr process group={terminated_process_group_id}",
                )
            clear_execution_control(session, task_id=job.task_id)
            clear_task_execution_progress(session, task_id=job.task_id)
        _mark_job_stale_failed(session, job)


def claim_next_job() -> ClaimedJob | None:
    with session_scope() as session:
        begin_queue_mutation(session)
        _recover_stale_running_jobs(session)
        running_gpu_job = session.exec(
            select(TaskJob).where(TaskJob.gpu_bound.is_(True)).where(TaskJob.status == "running")
        ).first()
        if running_gpu_job is not None:
            return None
        session.commit()
        queue_entry = claim_next_queue_entry(session)
        if queue_entry is None:
            return None

        job = session.exec(select(TaskJob).where(TaskJob.task_id == queue_entry.task_id)).first()
        task = session.get(Task, queue_entry.task_id)
        if job is None:
            finish_queue_entry(session, queue_entry.task_id)
            return None
        stage = session.exec(
            select(TaskStage)
            .where(TaskStage.task_id == queue_entry.task_id)
            .where(TaskStage.name == job.stage_name)
        ).first()
        if task is None or stage is None:
            finish_queue_entry(session, queue_entry.task_id)
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
        publish_task_updated(session, task)
        publish_stage_updated(session, stage)
        return ClaimedJob(task_id=job.task_id, stage_name=job.stage_name)


def complete_job(task_id: str, *, success: bool) -> None:
    with session_scope() as session:
        begin_queue_mutation(session)
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
        publish_task_updated(session, task)

        if stage is not None:
            stage.status = "success" if success else "failed"
            stage.finished_at = now
            stage.summary = "Completed by worker" if success else "Worker execution failed"
            stage.updated_at = now
            session.add(stage)
            publish_stage_updated(session, stage)
        pending_run = get_pending_pipeline_run(session, task_id)
        if pending_run is not None:
            start_pipeline_run(session, pending_run)
            if stage is not None:
                sync_stage_run(session, pending_run.id, stage)
            finish_pipeline_run(session, pending_run, "success" if success else "failed")
        finish_queue_entry(session, task_id)


def run_worker_iteration(processor: Callable[[ClaimedJob], bool] | None = None) -> ClaimedJob | None:
    claimed_job = claim_next_job()
    if claimed_job is None:
        return None
    if processor is None:
        preflight_runtime_summary = _surface_preflight_runtime_summary(claimed_job.task_id, claimed_job.stage_name)
        execution_token = f"exec-{uuid4().hex}"
        with session_scope() as session:
            activate_execution(session, task_id=claimed_job.task_id, execution_token=execution_token)
            try:
                try:
                    result = run_task_pipeline(
                        session,
                        claimed_job.task_id,
                        start_stage_name=claimed_job.stage_name,
                        claimed_stage_running=True,
                        execution_token=execution_token,
                    )
                except Exception:
                    begin_queue_mutation(session)
                    finish_queue_entry(session, claimed_job.task_id)
                    session.commit()
                    raise
                if result.final_status in {"success", "failed", "cancelled"}:
                    begin_queue_mutation(session)
                    finish_queue_entry(session, claimed_job.task_id)
                    session.commit()
            finally:
                if preflight_runtime_summary is not None:
                    append_stage_log(log_file_for_stage(claimed_job.task_id, claimed_job.stage_name), preflight_runtime_summary)
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
