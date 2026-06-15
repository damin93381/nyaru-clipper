from __future__ import annotations

from datetime import datetime, timezone

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
    "TaskExecutionControl",
    "TaskExecutionProgress",
    "TERMINAL_STATUSES",
    "Task",
    "TaskJob",
    "TaskStage",
    "utc_now",
]


class Task(SQLModel, table=True):
    id: str = Field(primary_key=True)
    source_url: str
    normalized_source_url: str = Field(index=True)
    source_video_id: str | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
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
