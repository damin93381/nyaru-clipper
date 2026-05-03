from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlmodel import Session, select

from app.models import (
    Artifact,
    CANONICAL_STAGES,
    Task,
    TaskExecutionProgress,
    TaskJob,
    TaskStage,
    TERMINAL_STATUSES,
    utc_now,
)
from app.services.storage import build_artifact_content_path, ensure_task_dirs, summarize_stage_log

BV_PATTERN = re.compile(r"(BV[0-9A-Za-z]+)", re.IGNORECASE)


@dataclass(slots=True)
class TaskRecord:
    task: Task
    stages: list[TaskStage]
    artifacts: list[Artifact]
    execution_progress: TaskExecutionProgress | None = None


def normalize_source_url(source_url: str) -> tuple[str, str | None]:
    match = BV_PATTERN.search(source_url)
    video_id = match.group(1) if match else None
    if video_id:
        return f"https://www.bilibili.com/video/{video_id}", video_id
    parsed = urlparse(source_url)
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.scheme and parsed.netloc else source_url
    return normalized.rstrip("/"), None


def _serialize_stage(stage: TaskStage) -> dict[str, Any]:
    return {
        "name": stage.name,
        "status": stage.status,
        "summary": stage.summary,
        "attempts": stage.attempts,
    }


def _serialize_artifact(artifact: Artifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "task_id": artifact.task_id,
        "stage_name": artifact.stage_name,
        "kind": artifact.kind,
        "path": build_artifact_content_path(
            task_id=artifact.task_id,
            artifact_id=int(artifact.id),
            artifact_path=artifact.path,
        ),
        "metadata_json": artifact.metadata_json,
    }


def _normalize_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _deserialize_progress_phases(phase_timings_json: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(phase_timings_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _serialize_execution_progress(progress: TaskExecutionProgress | None) -> dict[str, Any] | None:
    if progress is None:
        return None
    phase_started_at = _normalize_utc_datetime(progress.phase_started_at)
    heartbeat_at = _normalize_utc_datetime(progress.heartbeat_at)
    return {
        "stage_name": progress.stage_name,
        "current_phase": progress.current_phase,
        "phase_index": progress.phase_index,
        "phase_count": progress.phase_count,
        "phase_started_at": phase_started_at.isoformat() if phase_started_at else None,
        "heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
        "latest_message": progress.latest_message,
        "phases": _deserialize_progress_phases(progress.phase_timings_json),
    }


def _serialize_failure_recovery(task: Task, stages: list[TaskStage]) -> dict[str, Any] | None:
    if task.status != "failed":
        return None

    asr_stage = next((stage for stage in stages if stage.name == "asr"), None)
    if asr_stage is None or asr_stage.status != "failed" or asr_stage.summary != "missing_model":
        return None

    from app.services.asr_whisperx import build_asr_missing_model_recovery
    from app.settings import get_settings

    return build_asr_missing_model_recovery(get_settings())


def _task_to_response(task: Task, stages: list[TaskStage], *, created: bool | None = None) -> dict[str, Any]:
    payload = {
        "task_id": task.id,
        "source_url": task.source_url,
        "normalized_source_url": task.normalized_source_url,
        "source_video_id": task.source_video_id,
        "status": task.status,
        "stages": [_serialize_stage(stage) for stage in stages],
    }
    failure_recovery = _serialize_failure_recovery(task, stages)
    if failure_recovery is not None:
        payload["failure_recovery"] = failure_recovery
    if created is not None:
        payload["created"] = created
    return payload


def get_task_record(session: Session, task_id: str) -> TaskRecord | None:
    task = session.get(Task, task_id)
    if task is None:
        return None
    stages = session.exec(
        select(TaskStage).where(TaskStage.task_id == task_id).order_by(TaskStage.id)
    ).all()
    artifacts = session.exec(
        select(Artifact).where(Artifact.task_id == task_id).order_by(Artifact.id)
    ).all()
    execution_progress = session.get(TaskExecutionProgress, task_id)
    return TaskRecord(
        task=task,
        stages=stages,
        artifacts=artifacts,
        execution_progress=execution_progress,
    )


def upsert_task_execution_progress(
    session: Session,
    *,
    task_id: str,
    stage_name: str,
    current_phase: str,
    phase_index: int,
    phase_count: int,
    latest_message: str | None,
    phase_started_at: datetime | None,
    heartbeat_at: datetime | None,
    phase_timings: list[dict[str, Any]],
) -> TaskExecutionProgress:
    progress = session.get(TaskExecutionProgress, task_id)
    if progress is None:
        progress = TaskExecutionProgress(
            task_id=task_id,
            stage_name=stage_name,
            current_phase=current_phase,
            phase_index=phase_index,
            phase_count=phase_count,
            latest_message=latest_message,
            phase_started_at=phase_started_at,
            heartbeat_at=heartbeat_at,
            phase_timings_json=json.dumps(phase_timings, sort_keys=True),
        )
    else:
        progress.stage_name = stage_name
        progress.current_phase = current_phase
        progress.phase_index = phase_index
        progress.phase_count = phase_count
        progress.latest_message = latest_message
        progress.phase_started_at = phase_started_at
        progress.heartbeat_at = heartbeat_at
        progress.phase_timings_json = json.dumps(phase_timings, sort_keys=True)
    progress.updated_at = utc_now()
    session.add(progress)
    session.flush()
    return progress


def clear_task_execution_progress(session: Session, *, task_id: str) -> None:
    progress = session.get(TaskExecutionProgress, task_id)
    if progress is None:
        return
    session.delete(progress)
    session.flush()


def create_task(session: Session, source_url: str) -> tuple[dict[str, Any], bool]:
    normalized_url, video_id = normalize_source_url(source_url)
    existing = session.exec(
        select(Task)
        .where(Task.normalized_source_url == normalized_url)
        .where(Task.status.notin_(TERMINAL_STATUSES))
        .order_by(Task.created_at.desc())
    ).first()
    if existing is None and video_id is not None:
        existing = session.exec(
            select(Task)
            .where(Task.source_video_id == video_id)
            .where(Task.status.notin_(TERMINAL_STATUSES))
            .order_by(Task.created_at.desc())
        ).first()
    if existing is not None:
        record = get_task_record(session, existing.id)
        assert record is not None
        return _task_to_response(record.task, record.stages, created=False), False

    task_id = f"task-{uuid4().hex[:12]}"
    ensure_task_dirs(task_id)
    task = Task(
        id=task_id,
        source_url=source_url,
        normalized_source_url=normalized_url,
        source_video_id=video_id,
        status="pending",
    )
    session.add(task)
    session.flush()

    stages = [TaskStage(task_id=task_id, name=stage_name, status="pending") for stage_name in CANONICAL_STAGES]
    session.add_all(stages)
    session.add(TaskJob(task_id=task_id, stage_name=CANONICAL_STAGES[0], status="pending", gpu_bound=True))
    session.flush()
    for stage in stages:
        session.refresh(stage)
    session.refresh(task)
    return _task_to_response(task, stages, created=True), True


def get_task_detail(session: Session, task_id: str) -> dict[str, Any] | None:
    record = get_task_record(session, task_id)
    if record is None:
        return None
    payload = _task_to_response(record.task, record.stages)
    execution_progress = _serialize_execution_progress(record.execution_progress)
    if execution_progress is not None:
        payload["execution_progress"] = execution_progress
    return payload


def list_task_stages(session: Session, task_id: str) -> list[dict[str, Any]] | None:
    record = get_task_record(session, task_id)
    if record is None:
        return None
    return [_serialize_stage(stage) for stage in record.stages]


def list_task_artifacts(session: Session, task_id: str) -> list[dict[str, Any]] | None:
    record = get_task_record(session, task_id)
    if record is None:
        return None
    return [_serialize_artifact(artifact) for artifact in record.artifacts]


def get_task_artifact(session: Session, task_id: str, artifact_id: int) -> Artifact | None:
    artifact = session.get(Artifact, artifact_id)
    if artifact is None or artifact.task_id != task_id:
        return None
    return artifact


def list_task_log_summaries(session: Session, task_id: str) -> list[dict[str, Any]] | None:
    record = get_task_record(session, task_id)
    if record is None:
        return None
    return [
        {
            "stage_name": stage.name,
            "status": stage.status,
            "summary": summarize_stage_log(task_id, stage.name) or stage.summary,
            "log_path": str(Path("/data/tasks") / task_id / "logs" / f"{stage.name}.log"),
        }
        for stage in record.stages
    ]


def retry_task_from_stage(session: Session, task_id: str, stage_name: str) -> dict[str, Any] | None:
    record = get_task_record(session, task_id)
    if record is None:
        return None
    if stage_name not in CANONICAL_STAGES:
        raise ValueError(f"Unknown stage: {stage_name}")

    reset_index = CANONICAL_STAGES.index(stage_name)
    for stage in record.stages:
        stage_index = CANONICAL_STAGES.index(stage.name)
        if stage_index >= reset_index:
            stage.status = "pending"
            stage.summary = None
            stage.started_at = None
            stage.finished_at = None
            stage.updated_at = utc_now()
        session.add(stage)

    record.task.status = "pending"
    record.task.updated_at = utc_now()
    session.add(record.task)

    if reset_index <= CANONICAL_STAGES.index("asr"):
        clear_task_execution_progress(session, task_id=task_id)

    job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
    if job is None:
        job = TaskJob(task_id=task_id, stage_name=stage_name, status="pending", gpu_bound=True)
    else:
        job.stage_name = stage_name
        job.status = "pending"
        job.started_at = None
        job.finished_at = None
        job.updated_at = utc_now()
    session.add(job)
    session.flush()
    return {"task_id": task_id, "retry_stage": stage_name, "status": "pending"}
