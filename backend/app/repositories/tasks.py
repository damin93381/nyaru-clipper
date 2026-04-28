from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlmodel import Session, select

from app.models import Artifact, CANONICAL_STAGES, Task, TaskJob, TaskStage, TERMINAL_STATUSES, utc_now
from app.services.storage import build_artifact_content_path, ensure_task_dirs, summarize_stage_log

BV_PATTERN = re.compile(r"(BV[0-9A-Za-z]+)", re.IGNORECASE)


@dataclass(slots=True)
class TaskRecord:
    task: Task
    stages: list[TaskStage]
    artifacts: list[Artifact]


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
    return TaskRecord(task=task, stages=stages, artifacts=artifacts)


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
    return _task_to_response(record.task, record.stages)


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
