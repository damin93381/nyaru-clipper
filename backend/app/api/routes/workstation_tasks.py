"""Versioned task-library queries and metadata mutations."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ConfigDict, Field
from sqlalchemy import delete
from sqlmodel import Session

from app.api.schemas.workstation import TaskLibrarySummary, TaskListPage, TaskListQuery, TaskOverview, WorkstationSchema
from app.db import get_session
from app.models import Task, TaskTag, TaskTagLink, utc_now
from app.repositories.workstation import (
    get_task_library_summary,
    get_workstation_task_overview,
    list_workstation_tasks,
)


router = APIRouter(prefix="/v2/tasks", tags=["workstation-tasks"])

BulkTaskOperation: TypeAlias = Literal["archive", "unarchive", "delete"]


class TaskPatchRequest(WorkstationSchema):
    """Editable task-library metadata, with absent fields left unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    tags: list[Annotated[str, Field(min_length=1, max_length=80)]] | None = None
    archived: bool | None = None


class BulkTaskMutationRequest(WorkstationSchema):
    """One explicit operation over task identifiers in request order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: BulkTaskOperation
    task_ids: Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]


class BulkTaskMutationResult(WorkstationSchema):
    """The independently observable outcome for one bulk task identifier."""

    task_id: str
    status: Literal["success", "not_found", "rejected"]
    message: str | None


class BulkTaskMutationResponse(WorkstationSchema):
    """Ordered outcomes for a bulk task mutation."""

    results: list[BulkTaskMutationResult]


@router.get("", response_model=TaskListPage)
def list_task_library_endpoint(
    query: Annotated[TaskListQuery, Query()],
    session: Session = Depends(get_session),
) -> TaskListPage:
    """Return the requested bounded library page."""
    return list_workstation_tasks(session, query)


@router.get("/summary", response_model=TaskLibrarySummary)
def task_library_summary_endpoint(session: Session = Depends(get_session)) -> TaskLibrarySummary:
    """Return task-library dashboard counters."""
    return get_task_library_summary(session)


@router.post("/bulk", response_model=BulkTaskMutationResponse)
def bulk_task_mutation_endpoint(
    payload: BulkTaskMutationRequest,
    session: Session = Depends(get_session),
) -> BulkTaskMutationResponse:
    """Apply one archive, unarchive, or deletion operation per requested task."""
    results = [_bulk_result(session, task_id, payload.operation) for task_id in payload.task_ids]
    session.commit()
    return BulkTaskMutationResponse(results=results)


@router.get("/{task_id}", response_model=TaskOverview)
def task_library_overview_endpoint(task_id: str, session: Session = Depends(get_session)) -> TaskOverview:
    """Return one complete task-library overview."""
    overview = get_workstation_task_overview(session, task_id)
    if overview is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return overview


@router.patch("/{task_id}", response_model=TaskOverview)
def patch_task_library_endpoint(
    task_id: str,
    payload: TaskPatchRequest,
    session: Session = Depends(get_session),
) -> TaskOverview:
    """Replace the requested editable task metadata fields."""
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    _apply_task_patch(session, task, payload)
    session.commit()

    overview = get_workstation_task_overview(session, task_id)
    if overview is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return overview


def _apply_task_patch(session: Session, task: Task, payload: TaskPatchRequest) -> None:
    """Apply present fields only, replacing tag membership atomically in the session."""
    if "title" in payload.model_fields_set:
        task.title = payload.title
    if "archived" in payload.model_fields_set:
        task.archived_at = utc_now() if payload.archived else None
    if "tags" in payload.model_fields_set:
        session.exec(delete(TaskTagLink).where(TaskTagLink.task_id == task.id))
        for tag_name in sorted(set(payload.tags or [])):
            if session.get(TaskTag, tag_name) is None:
                session.add(TaskTag(name=tag_name))
            session.add(TaskTagLink(task_id=task.id, tag_name=tag_name))
    task.updated_at = utc_now()
    session.add(task)


def _bulk_result(session: Session, task_id: str, operation: BulkTaskOperation) -> BulkTaskMutationResult:
    """Apply one requested bulk operation without preventing adjacent task outcomes."""
    task = session.get(Task, task_id)
    if task is None:
        return BulkTaskMutationResult(task_id=task_id, status="not_found", message="Task not found")

    match operation:
        case "archive":
            task.archived_at = utc_now()
            task.updated_at = utc_now()
            session.add(task)
        case "unarchive":
            task.archived_at = None
            task.updated_at = utc_now()
            session.add(task)
        case "delete":
            is_active = task.status == "running"
            if is_active:
                return BulkTaskMutationResult(task_id=task_id, status="rejected", message="Task is actively running")
            session.exec(delete(TaskTagLink).where(TaskTagLink.task_id == task.id))
            session.delete(task)
    return BulkTaskMutationResult(task_id=task_id, status="success", message=None)
