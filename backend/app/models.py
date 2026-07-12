from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


CANONICAL_STAGES = [
    "ingest",
    "media_prep",
    "asr",
    "translation",
    "highlight",
    "export",
    "report",
]

TERMINAL_STATUSES = ["success", "failed", "cancelled"]

__all__ = [
    "Artifact",
    "CANONICAL_STAGES",
    "ClipCandidate",
    "MediaSource",
    "PipelineRun",
    "QueueEntry",
    "QueueState",
    "StageRun",
    "TaskExecutionControl",
    "TaskExecutionProgress",
    "TaskTag",
    "TaskTagLink",
    "TERMINAL_STATUSES",
    "Task",
    "TaskJob",
    "TaskStage",
    "WorkstationEvent",
    "utc_now",
]


class Task(SQLModel, table=True):
    id: str = Field(primary_key=True)
    source_url: str
    normalized_source_url: str = Field(index=True)
    source_video_id: str | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
    title: str | None = Field(default=None)
    archived_at: datetime | None = Field(default=None)
    storage_bytes: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TaskJob(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, foreign_key="task.id")
    stage_name: str
    status: str = Field(default="pending", index=True)
    gpu_bound: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)


class TaskStage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, foreign_key="task.id")
    name: str = Field(index=True)
    status: str = Field(default="pending", index=True)
    summary: str | None = Field(default=None)
    failure_code: str | None = Field(default=None, index=True)
    attempts: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)


class TaskExecutionProgress(SQLModel, table=True):
    task_id: str = Field(primary_key=True, foreign_key="task.id")
    stage_name: str = Field(index=True)
    current_phase: str
    phase_index: int
    phase_count: int
    latest_message: str | None = Field(default=None)
    phase_started_at: datetime | None = Field(default=None)
    heartbeat_at: datetime | None = Field(default=None)
    phase_timings_json: str = Field(default="[]")
    updated_at: datetime = Field(default_factory=utc_now)


class TaskExecutionControl(SQLModel, table=True):
    task_id: str = Field(primary_key=True, foreign_key="task.id")
    execution_token: str | None = Field(default=None, index=True)
    active_process_group_id: int | None = Field(default=None)
    cancel_requested: bool = Field(default=False, index=True)
    force_kill_requested: bool = Field(default=False)
    heartbeat_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Artifact(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, foreign_key="task.id")
    stage_name: str = Field(index=True)
    kind: str = Field(index=True)
    path: str
    metadata_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utc_now)


class ClipCandidate(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, foreign_key="task.id")
    start_seconds: float
    end_seconds: float
    score: float
    reason: str
    status: str = Field(default="candidate", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MediaSource(SQLModel, table=True):
    """The stable source identity associated with one workstation task."""

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(unique=True, index=True, foreign_key="task.id")
    kind: str = Field(index=True)
    locator: str
    display_name: str | None = Field(default=None)
    source_video_id: str | None = Field(default=None, index=True)
    import_mode: str = Field(default="managed")
    metadata_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utc_now)


class TaskTag(SQLModel, table=True):
    """A user-defined tag available to workstation tasks."""

    name: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utc_now)


class TaskTagLink(SQLModel, table=True):
    """A unique association between a task and one tag."""

    __table_args__ = (UniqueConstraint("task_id", "tag_name", name="uq_tasktaglink_task_tag"),)

    task_id: str = Field(primary_key=True, foreign_key="task.id")
    tag_name: str = Field(primary_key=True, foreign_key="tasktag.name")


class QueueState(SQLModel, table=True):
    """The singleton revision counter for queue mutations."""

    id: int = Field(default=1, primary_key=True)
    revision: int = Field(default=1)
    updated_at: datetime = Field(default_factory=utc_now)


class QueueEntry(SQLModel, table=True):
    """The workstation queue projection for a task."""

    task_id: str = Field(primary_key=True, foreign_key="task.id")
    position: int = Field(index=True)
    priority: int = Field(default=0, index=True)
    state: str = Field(default="queued", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PipelineRun(SQLModel, table=True):
    """One user-visible execution of a task pipeline."""

    id: str = Field(primary_key=True)
    task_id: str = Field(index=True, foreign_key="task.id")
    status: str = Field(index=True)
    trigger: str = Field(default="create")
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)


class StageRun(SQLModel, table=True):
    """A stage-level execution record within a pipeline run."""

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, foreign_key="pipelinerun.id")
    name: str = Field(index=True)
    status: str = Field(index=True)
    summary: str | None = Field(default=None)
    failure_code: str | None = Field(default=None, index=True)
    attempts: int = Field(default=0)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)


class WorkstationEvent(SQLModel, table=True):
    """A durable, public-safe workstation state transition for SSE clients."""

    id: int | None = Field(default=None, primary_key=True)
    event_type: str = Field(index=True)
    entity_id: str = Field(index=True)
    payload_json: str
    created_at: datetime = Field(default_factory=utc_now, index=True)
