from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from sqlmodel import Session

from app.db import get_session
from app.repositories.tasks import (
    create_task,
    get_task_artifact,
    get_task_detail,
    list_task_artifacts,
    list_task_log_summaries,
    list_task_stages,
    retry_task_from_stage,
)
from app.services.clip_export import ClipExportFailure, export_confirmed_clip
from app.services.storage import build_artifact_content_path, resolve_task_artifact_path

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    source_url: HttpUrl


class RetryTaskRequest(BaseModel):
    stage_name: str


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
def task_detail_endpoint(task_id: str, session: Session = Depends(get_session)) -> dict:
    task = get_task_detail(session, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


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
