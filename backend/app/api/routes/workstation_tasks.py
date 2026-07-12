"""Versioned task-library queries and metadata mutations."""

from __future__ import annotations

import json
from typing import Annotated, Literal, TypeAlias
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ConfigDict, Field, HttpUrl
from sqlmodel import Session

from app.api.schemas.workstation import TaskLibrarySummary, TaskListPage, TaskListQuery, TaskOverview, WorkstationSchema
from app.db import get_session
from app.models import CANONICAL_STAGES, MediaSource, StageRun, Task, TaskJob, TaskStage
from app.repositories.workstation import (
    get_task_library_summary,
    get_workstation_task_overview,
    list_workstation_tasks,
)
from app.repositories.tasks import normalize_bilibili_source_url
from app.services.source_catalog import SourceCatalogError, resolve_local_media_source
from app.services.storage import ensure_task_dirs
from app.services.task_library_lifecycle import (
    TaskBulkOperation,
    TaskMetadataPatch,
    apply_task_bulk_mutation,
    patch_task_metadata,
)
from app.services.workstation_events import publish_event
from app.services.workstation_queue import begin_queue_mutation, enqueue_task
from app.services.workstation_runs import create_pipeline_run


router = APIRouter(prefix="/v2/tasks", tags=["workstation-tasks"])


class BilibiliTaskSource(WorkstationSchema):
    """A Bilibili source selected by URL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["bilibili"]
    url: HttpUrl


class LocalTaskSource(WorkstationSchema):
    """A selected supported file within a configured local import root."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["local"]
    root_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    import_mode: Literal["reference"]


TaskSource: TypeAlias = Annotated[BilibiliTaskSource | LocalTaskSource, Field(discriminator="kind")]


class CreateWorkstationTaskRequest(WorkstationSchema):
    """The v2 source, profile, and scheduling request for one new task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: TaskSource
    profile_id: Literal["standard"]
    priority: int = 0


class CreateWorkstationTaskResponse(WorkstationSchema):
    """The accepted v2 task identity and selected scheduling options."""

    task_id: str
    profile_id: Literal["standard"]
    priority: int
    status: Literal["pending"]


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


@router.post("", response_model=CreateWorkstationTaskResponse, status_code=201)
def create_workstation_task_endpoint(
    payload: CreateWorkstationTaskRequest,
    session: Session = Depends(get_session),
) -> CreateWorkstationTaskResponse:
    """Create all legacy and workstation task records in one database transaction."""
    try:
        task = _create_workstation_task(session, payload)
    except SourceCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return CreateWorkstationTaskResponse(
        task_id=task.id,
        profile_id=payload.profile_id,
        priority=payload.priority,
        status="pending",
    )


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


def _create_workstation_task(session: Session, payload: CreateWorkstationTaskRequest) -> Task:
    """Persist a fully projected pending task after resolving its discriminated source."""
    task_id = f"task-{uuid4().hex[:12]}"
    source_url, normalized_source_url, source_video_id, media_source = _task_source(task_id, payload.source)
    begin_queue_mutation(session)
    ensure_task_dirs(task_id)
    task = Task(
        id=task_id,
        source_url=source_url,
        normalized_source_url=normalized_source_url,
        source_video_id=source_video_id,
        status="pending",
        title=media_source.display_name,
    )
    session.add(task)
    session.add(media_source)
    session.add_all([TaskStage(task_id=task_id, name=stage_name, status="pending") for stage_name in CANONICAL_STAGES])
    session.add(TaskJob(task_id=task_id, stage_name=CANONICAL_STAGES[0], status="pending", gpu_bound=True))
    run = create_pipeline_run(session, task_id, "create")
    session.add_all([StageRun(run_id=run.id, name=stage_name, status="pending") for stage_name in CANONICAL_STAGES])
    queue_entry = enqueue_task(session, task_id)
    queue_entry.priority = payload.priority
    session.add(queue_entry)
    publish_event(session, "task.created", task_id, {"task_id": task_id, "status": task.status})
    session.flush()
    return task


def _task_source(task_id: str, source: TaskSource) -> tuple[str, str, str | None, MediaSource]:
    match source:
        case BilibiliTaskSource(url=url):
            normalized_url, source_video_id = normalize_bilibili_source_url(str(url))
            media_source = MediaSource(
                task_id=task_id,
                kind="bilibili",
                locator=normalized_url,
                display_name=source_video_id,
                source_video_id=source_video_id,
                import_mode="managed",
            )
            return normalized_url, normalized_url, source_video_id, media_source
        case LocalTaskSource(root_id=root_id, relative_path=relative_path, import_mode=import_mode):
            local_source = resolve_local_media_source(root_id, relative_path)
            locator = f"local://{local_source.root_id}/{local_source.relative_path}"
            media_source = MediaSource(
                task_id=task_id,
                kind="local",
                locator=locator,
                display_name=local_source.path.name,
                import_mode=import_mode,
                metadata_json=json.dumps(
                    {"relative_path": local_source.relative_path, "root_id": local_source.root_id}, sort_keys=True
                ),
            )
            return locator, locator, None, media_source
