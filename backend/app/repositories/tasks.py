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
from app.services.failure_codes import failure_code_from_stage
from app.services.recovery_actions import serialize_recovery_actions, stage_display_label
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
        "failure_code": failure_code_from_stage(stage),
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
    if asr_stage is None or asr_stage.status != "failed" or failure_code_from_stage(asr_stage) != "asr_missing_model":
        return None

    from app.services.asr_whisperx import build_asr_missing_model_recovery
    from app.settings import get_settings

    return build_asr_missing_model_recovery(get_settings())


def _task_failure_code(task: Task, stages: list[TaskStage]) -> str | None:
    if task.status != "failed":
        return None
    failed_stage = next((stage for stage in stages if stage.status == "failed"), None)
    if failed_stage is None:
        return "unknown_failure"
    return failure_code_from_stage(failed_stage) or "unknown_failure"


_EXPECTED_ARTIFACT_KINDS = {
    "ingest": ("source_video", ("source_video",)),
    "media_prep": ("prepared_audio", ("prepared_audio", "asr_audio")),
    "asr": ("transcript_json", ("transcript_json",)),
    "translation": ("translated_segments", ("translated_segments", "bilingual_transcript_json")),
    "highlight": ("highlight_candidates", ("highlight_candidates", "highlight_candidates_json")),
    "export": ("clip_video", ("clip_video", "exported_clip")),
    "report": ("report", ("report", "task_report_markdown")),
}


def _artifact_readiness_status(stage: TaskStage, *, artifact: Artifact | None) -> str:
    if artifact is not None and Path(artifact.path).exists():
        return "ready"
    if stage.status == "failed":
        return "failed"
    if stage.status == "success":
        return "missing"
    return "not_ready"


def _serialize_artifact_readiness(stages: list[TaskStage], artifacts: list[Artifact]) -> list[dict[str, Any]]:
    artifact_by_stage_kind: dict[tuple[str, str], Artifact] = {}
    for artifact in artifacts:
        artifact_by_stage_kind[(artifact.stage_name, artifact.kind)] = artifact

    items: list[dict[str, Any]] = []
    for stage in stages:
        if stage.name not in _EXPECTED_ARTIFACT_KINDS:
            continue
        public_kind, stored_kinds = _EXPECTED_ARTIFACT_KINDS[stage.name]
        artifact = next(
            (artifact_by_stage_kind.get((stage.name, stored_kind)) for stored_kind in stored_kinds if artifact_by_stage_kind.get((stage.name, stored_kind)) is not None),
            None,
        )
        artifact_id = int(artifact.id) if artifact is not None and artifact.id is not None else None
        items.append(
            {
                "stage_name": stage.name,
                "kind": public_kind,
                "status": _artifact_readiness_status(stage, artifact=artifact),
                "artifact_id": artifact_id,
                "path": build_artifact_content_path(
                    task_id=artifact.task_id,
                    artifact_id=artifact_id,
                    artifact_path=artifact.path,
                )
                if artifact is not None and artifact_id is not None
                else None,
            }
        )
        if stage.status == "failed":
            break
    return items


def _task_to_response(
    task: Task,
    stages: list[TaskStage],
    *,
    artifacts: list[Artifact] | None = None,
    created: bool | None = None,
) -> dict[str, Any]:
    payload = {
        "task_id": task.id,
        "source_url": task.source_url,
        "normalized_source_url": task.normalized_source_url,
        "source_video_id": task.source_video_id,
        "status": task.status,
        "failure_code": _task_failure_code(task, stages),
        "recovery_actions": serialize_recovery_actions(task_id=task.id, task_status=task.status, stages=stages),
        "stages": [_serialize_stage(stage) for stage in stages],
    }
    if artifacts is not None:
        payload["artifact_readiness"] = _serialize_artifact_readiness(stages, artifacts)
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
        return _task_to_response(record.task, record.stages, artifacts=record.artifacts, created=False), False

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
    from app.services.workstation_queue import enqueue_task
    from app.services.workstation_runs import create_pipeline_run

    enqueue_task(session, task_id)
    create_pipeline_run(session, task_id, "create")
    session.flush()
    for stage in stages:
        session.refresh(stage)
    session.refresh(task)
    return _task_to_response(task, stages, artifacts=[], created=True), True


def get_task_detail(session: Session, task_id: str) -> dict[str, Any] | None:
    record = get_task_record(session, task_id)
    if record is None:
        return None
    payload = _task_to_response(record.task, record.stages, artifacts=record.artifacts)
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
    summaries: list[dict[str, Any]] = []
    for stage in record.stages:
        summary = summarize_stage_log(task_id, stage.name) or stage.summary
        summaries.append(
            {
                "stage_name": stage.name,
                "status": stage.status,
                "summary": summary,
                "display_label": stage_display_label(stage.name),
                "safe_summary": _redact_log_summary(summary),
                "log_path": str(Path("/data/tasks") / task_id / "logs" / f"{stage.name}.log"),
            }
        )
    return summaries


def _redact_log_summary(summary: str | None) -> str | None:
    if summary is None:
        return None
    redacted = re.sub(r"(?i)(token|secret|password|cookie|key)\s*[=:]\s*\S+", r"\1 [redacted]", summary)
    redacted = re.sub(r"(?i)\b(token|secret|password|cookie|key)\s+[A-Za-z0-9._~+/=-]{4,}\b", r"\1 [redacted]", redacted)
    redacted = re.sub(r"(?<!\w)/(?:home|tmp|var|mnt|data|Users)/[^\s]+", "[path]", redacted)
    redacted = re.sub(r"\$[A-Z_][A-Z0-9_]*", "[env]", redacted)
    return redacted


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
            stage.failure_code = None
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
    from app.services.workstation_queue import requeue_task
    from app.services.workstation_runs import create_pipeline_run

    create_pipeline_run(session, task_id, "retry")
    requeue_task(session, task_id)
    session.flush()
    return {"task_id": task_id, "retry_stage": stage_name, "status": "pending"}
