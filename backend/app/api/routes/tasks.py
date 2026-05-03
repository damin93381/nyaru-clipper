from __future__ import annotations

import mimetypes
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from sqlmodel import Session

from app.db import get_session
from app.models import TaskExecutionControl
from app.repositories.tasks import (
    create_task,
    get_task_artifact,
    get_task_detail,
    get_task_record,
    list_task_artifacts,
    list_task_log_summaries,
    list_task_stages,
    retry_task_from_stage,
)
from app.services.clip_export import ClipExportFailure, export_confirmed_clip
from app.services.asr_whisperx import download_asr_missing_models
from app.services.storage import build_artifact_content_path, resolve_task_artifact_path
from app.services.task_control import can_force_kill, request_cancel, request_force_kill
from app.settings import get_settings

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _load_task_execution_control(session: Session, *, task_id: str) -> TaskExecutionControl | None:
    return session.get(TaskExecutionControl, task_id)


def _overlay_control_status(detail: dict[str, Any], *, control: TaskExecutionControl | None) -> dict[str, Any]:
    if control is None:
        return detail
    if detail.get("status") == "running" and (control.cancel_requested or control.force_kill_requested):
        detail = dict(detail)
        detail["status"] = "cancel_requested"
    return detail


class CreateTaskRequest(BaseModel):
    source_url: HttpUrl


class RetryTaskRequest(BaseModel):
    stage_name: str


class DownloadAsrModelsRequest(BaseModel):
    model_keys: list[Literal["whisperx", "alignment"]]


class ExportClipRequest(BaseModel):
    candidate_id: int
    start_s: float | None = None
    end_s: float | None = None


@router.post("")
def create_task_endpoint(
    payload: CreateTaskRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    task_payload, created = create_task(session, str(payload.source_url))
    session.commit()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return task_payload


@router.get("/{task_id}")
def task_detail_endpoint(task_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    task = get_task_detail(session, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    control = _load_task_execution_control(session, task_id=task_id)
    return _overlay_control_status(task, control=control)


@router.post("/{task_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
def task_cancel_endpoint(task_id: str, session: Session = Depends(get_session)) -> dict[str, str]:
    record = get_task_record(session, task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    try:
        request_cancel(session, task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task is not actively cancellable") from exc
    return {"task_id": task_id, "status": "cancel_requested"}


@router.post("/{task_id}/force-kill", status_code=status.HTTP_202_ACCEPTED)
def task_force_kill_endpoint(task_id: str, session: Session = Depends(get_session)) -> dict[str, str]:
    record = get_task_record(session, task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if not can_force_kill(session, task_id=task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task is not currently force-killable",
        )
    try:
        request_force_kill(session, task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task is not actively cancellable") from exc
    return {"task_id": task_id, "status": "cancel_requested"}


@router.get("/{task_id}/stages")
def task_stages_endpoint(task_id: str, session: Session = Depends(get_session)) -> list[dict]:
    stages = list_task_stages(session, task_id)
    if stages is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return stages


@router.get("/{task_id}/artifacts")
def task_artifacts_endpoint(task_id: str, session: Session = Depends(get_session)) -> list[dict]:
    artifacts = list_task_artifacts(session, task_id)
    if artifacts is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return artifacts


@router.get("/{task_id}/artifacts/{artifact_id}/content/{filename}")
def task_artifact_content_endpoint(task_id: str, artifact_id: int, filename: str, session: Session = Depends(get_session)) -> FileResponse:
    artifact = get_task_artifact(session, task_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    try:
        artifact_path = resolve_task_artifact_path(task_id, artifact.path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found") from exc

    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact file not found")

    media_type = mimetypes.guess_type(str(artifact_path))[0] or "application/octet-stream"
    return FileResponse(artifact_path, filename=filename, media_type=media_type)


@router.get("/{task_id}/logs")
def task_logs_endpoint(task_id: str, session: Session = Depends(get_session)) -> list[dict]:
    logs = list_task_log_summaries(session, task_id)
    if logs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return logs


@router.post("/{task_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def task_retry_endpoint(
    task_id: str,
    payload: RetryTaskRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        retry_result = retry_task_from_stage(session, task_id, payload.stage_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if retry_result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    session.commit()
    return retry_result


@router.post("/{task_id}/asr/models/download", status_code=status.HTTP_202_ACCEPTED)
def task_asr_model_download_endpoint(
    task_id: str,
    payload: DownloadAsrModelsRequest,
    session: Session = Depends(get_session),
) -> dict:
    record = get_task_record(session, task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    asr_stage = next((stage for stage in record.stages if stage.name == "asr"), None)
    if record.task.status != "failed" or asr_stage is None or asr_stage.status != "failed" or asr_stage.summary != "missing_model":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ASR task is not awaiting missing-model recovery")

    return download_asr_missing_models(get_settings(), requested_keys=payload.model_keys)


@router.post("/{task_id}/clips", status_code=status.HTTP_201_CREATED)
def task_clip_export_endpoint(
    task_id: str,
    payload: ExportClipRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        result = export_confirmed_clip(
            session,
            task_id,
            candidate_id=payload.candidate_id,
            start_s=payload.start_s,
            end_s=payload.end_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ClipExportFailure as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    session.commit()
    return {
        "task_id": result.task_id,
        "candidate_id": result.candidate_id,
        "start_s": result.start_s,
        "end_s": result.end_s,
        "path": build_artifact_content_path(
            task_id=result.task_id,
            artifact_id=result.artifact_id,
            artifact_path=result.output_path,
        ),
        "filename": result.output_path.name,
        "artifact_id": result.artifact_id,
    }
