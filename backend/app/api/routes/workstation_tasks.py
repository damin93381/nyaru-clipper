"""Versioned task-library queries and metadata mutations."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ConfigDict, Field
from sqlmodel import Session

from app.api.schemas.workstation import TaskLibrarySummary, TaskListPage, TaskListQuery, TaskOverview, WorkstationSchema
from app.db import get_session
from app.repositories.workstation import (
    get_task_library_summary,
    get_workstation_task_overview,
    list_workstation_tasks,
)
from app.services.task_library_lifecycle import (
    TaskBulkOperation,
    TaskMetadataPatch,
    apply_task_bulk_mutation,
    patch_task_metadata,
)


router = APIRouter(prefix="/v2/tasks", tags=["workstation-tasks"])


class TaskPatchRequest(WorkstationSchema):
    """Editable task-library metadata, with absent fields left unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    tags: list[Annotated[str, Field(min_length=1, max_length=80)]] | None = None
    archived: bool | None = None


class BulkTaskMutationRequest(WorkstationSchema):
    """One explicit operation over task identifiers in request order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: TaskBulkOperation
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
    results = [apply_task_bulk_mutation(session, task_id, payload.operation) for task_id in payload.task_ids]
    session.commit()
    return BulkTaskMutationResponse(
        results=[
            BulkTaskMutationResult(task_id=result.task_id, status=result.status, message=result.message)
            for result in results
        ]
    )


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
    patch = TaskMetadataPatch(
        title=payload.title,
        tags=tuple(payload.tags) if payload.tags is not None else None,
        archived=payload.archived,
        updates_title="title" in payload.model_fields_set,
        updates_tags="tags" in payload.model_fields_set,
        updates_archive="archived" in payload.model_fields_set,
    )
    task = patch_task_metadata(session, task_id, patch)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    session.commit()

    overview = get_workstation_task_overview(session, task_id)
    if overview is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return overview
