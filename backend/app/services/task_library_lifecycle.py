"""Database-only mutations for workstation task-library metadata and lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias, assert_never

from sqlalchemy import delete
from sqlmodel import Session, select

from app.models import (
    Artifact,
    ClipCandidate,
    MediaSource,
    PipelineRun,
    StageRun,
    Task,
    TaskExecutionControl,
    TaskExecutionProgress,
    TaskJob,
    TaskStage,
    TaskTag,
    TaskTagLink,
    utc_now,
)
from app.services.workstation_events import publish_event, publish_task_updated


TaskBulkOperation: TypeAlias = Literal["archive", "unarchive", "delete"]
TaskBulkMutationStatus: TypeAlias = Literal["success", "not_found", "rejected"]


@dataclass(frozen=True, slots=True)
class TaskMetadataPatch:
    """Typed editable fields, with flags that preserve omitted-field semantics."""

    title: str | None
    tags: tuple[str, ...] | None
    archived: bool | None
    updates_title: bool
    updates_tags: bool
    updates_archive: bool


@dataclass(frozen=True, slots=True)
class TaskBulkMutationOutcome:
    """The service-level result for one requested task identifier."""

    task_id: str
    status: TaskBulkMutationStatus
    message: str | None


def patch_task_metadata(session: Session, task_id: str, patch: TaskMetadataPatch) -> Task | None:
    """Update requested metadata fields without committing the caller's transaction."""
    task = session.get(Task, task_id)
    if task is None:
        return None

    if patch.updates_title:
        task.title = patch.title
    if patch.updates_archive:
        task.archived_at = utc_now() if patch.archived else None
    if patch.updates_tags:
        session.exec(delete(TaskTagLink).where(TaskTagLink.task_id == task.id))
        for tag_name in sorted(set(patch.tags or ())):
            if session.get(TaskTag, tag_name) is None:
                session.add(TaskTag(name=tag_name))
            session.add(TaskTagLink(task_id=task.id, tag_name=tag_name))
    task.updated_at = utc_now()
    session.add(task)
    publish_task_updated(session, task)
    return task


def apply_task_bulk_mutation(
    session: Session,
    task_id: str,
    operation: TaskBulkOperation,
) -> TaskBulkMutationOutcome:
    """Apply one operation without committing, preserving independent batch outcomes."""
    task = session.get(Task, task_id)
    if task is None:
        return TaskBulkMutationOutcome(task_id=task_id, status="not_found", message="Task not found")

    match operation:
        case "archive":
            task.archived_at = utc_now()
            task.updated_at = utc_now()
            session.add(task)
            publish_task_updated(session, task)
        case "unarchive":
            task.archived_at = None
            task.updated_at = utc_now()
            session.add(task)
            publish_task_updated(session, task)
        case "delete":
            task_is_active = task.status == "running"
            if task_is_active:
                return TaskBulkMutationOutcome(
                    task_id=task_id,
                    status="rejected",
                    message="Task is actively running",
                )
            _delete_task_owned_database_rows(session, task)
        case unreachable:
            assert_never(unreachable)
    return TaskBulkMutationOutcome(task_id=task_id, status="success", message=None)


def _delete_task_owned_database_rows(session: Session, task: Task) -> None:
    """Delete all known database dependents; this bulk API intentionally does not delete managed files."""
    pipeline_run_ids = select(PipelineRun.id).where(PipelineRun.task_id == task.id)
    from app.services.workstation_queue import delete_queue_entry

    delete_queue_entry(session, task.id)
    session.exec(delete(StageRun).where(StageRun.run_id.in_(pipeline_run_ids)))
    session.exec(delete(PipelineRun).where(PipelineRun.task_id == task.id))
    session.exec(delete(TaskTagLink).where(TaskTagLink.task_id == task.id))
    session.exec(delete(MediaSource).where(MediaSource.task_id == task.id))
    session.exec(delete(TaskExecutionControl).where(TaskExecutionControl.task_id == task.id))
    session.exec(delete(TaskExecutionProgress).where(TaskExecutionProgress.task_id == task.id))
    session.exec(delete(ClipCandidate).where(ClipCandidate.task_id == task.id))
    session.exec(delete(Artifact).where(Artifact.task_id == task.id))
    session.exec(delete(TaskStage).where(TaskStage.task_id == task.id))
    session.exec(delete(TaskJob).where(TaskJob.task_id == task.id))
    publish_event(session, "task.deleted", task.id, {"task_id": task.id})
    session.delete(task)
