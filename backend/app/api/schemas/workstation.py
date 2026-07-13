"""Transport contracts for the versioned workstation task APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue


TaskStatus: TypeAlias = Literal["pending", "running", "success", "failed", "cancelled"]
StageStatus: TypeAlias = Literal[
    "pending",
    "planned",
    "running",
    "success",
    "failed",
    "cancelled",
    "skipped",
]
TaskSort: TypeAlias = Literal["updated_at", "created_at", "title", "storage_bytes"]
SortDirection: TypeAlias = Literal["asc", "desc"]
ArtifactReadinessStatus: TypeAlias = Literal["ready", "missing", "failed", "not_ready"]


class WorkstationSchema(BaseModel):
    """Immutable base for v2 JSON contracts."""

    model_config = ConfigDict(frozen=True)


class TaskListQuery(WorkstationSchema):
    """Validated server-side filters for the task library."""

    query: str | None = None
    statuses: list[TaskStatus] = Field(default_factory=list)
    source_kind: str | None = None
    tag: str | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    readiness: ArtifactReadinessStatus | None = None
    sort: TaskSort = "updated_at"
    direction: SortDirection = "desc"
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1)] = 50
    include_archived: bool = False


class TaskListItem(WorkstationSchema):
    """A bounded task-library row."""

    task_id: str
    title: str
    source_kind: str
    source_label: str
    status: TaskStatus
    current_stage: str | None
    progress_percent: Annotated[int, Field(ge=0, le=100)]
    tags: list[str]
    storage_bytes: Annotated[int, Field(ge=0)]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class TaskListPage(WorkstationSchema):
    """A page of task-library rows and its exact SQL count."""

    items: list[TaskListItem]
    page: int
    page_size: int
    total: int
    page_count: int


class TaskLibrarySummary(WorkstationSchema):
    """Dashboard counters for the complete task library."""

    active: Annotated[int, Field(ge=0)]
    queued: Annotated[int, Field(ge=0)]
    review_required: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]
    archived: Annotated[int, Field(ge=0)]
    storage_bytes: Annotated[int, Field(ge=0)]


class TaskStageOverview(WorkstationSchema):
    """One ordered pipeline-stage projection for a task overview."""

    name: str
    status: StageStatus
    summary: str | None
    failure_code: str | None
    attempts: Annotated[int, Field(ge=0)]
    started_at: datetime | None
    finished_at: datetime | None
    planned: bool


class ExecutionProgressOverview(WorkstationSchema):
    """Current worker progress, when a stage reports it."""

    stage_name: str
    current_phase: str
    phase_index: Annotated[int, Field(ge=0)]
    phase_count: Annotated[int, Field(ge=0)]
    latest_message: str | None
    phase_started_at: datetime | None
    heartbeat_at: datetime | None
    phases: list[dict[str, JsonValue]]


class ArtifactReadinessOverview(WorkstationSchema):
    """The availability state for the stage's expected public artifact."""

    stage_name: str
    kind: str
    status: ArtifactReadinessStatus
    artifact_id: int | None
    path: str | None


class TaskArtifactOverview(WorkstationSchema):
    """A public artifact reference without a raw host path."""

    artifact_id: int
    stage_name: str
    kind: str
    path: str
    metadata_json: str
    created_at: datetime


class SafeLogOverview(WorkstationSchema):
    """A redacted stage-log summary safe to disclose to the workstation UI."""

    stage_name: str
    status: StageStatus
    summary: str | None
    display_label: str


class RecoveryActionSchema(WorkstationSchema):
    """Closed action contract: unknown action and payload fields are rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RetryStageRecoveryPayload(RecoveryActionSchema):
    """The one required parameter for a stage-retry action."""

    stage_name: str


class DownloadAsrModelRecoveryPayload(RecoveryActionSchema):
    """The model cache keys required by an ASR model download."""

    model_keys: list[Literal["whisperx", "alignment"]]


class RetryStageRecoveryAction(RecoveryActionSchema):
    """Retry the failed stage selected by the backend."""

    id: Literal["retry_stage"]
    label_key: Literal["retry_stage"]
    description_key: Literal["retry_stage"]
    enabled: bool
    disabled_reason: str | None
    method: Literal["POST"]
    endpoint: str
    payload: RetryStageRecoveryPayload
    confirmation_required: Literal[False]
    success_behavior: Literal["poll_task"]


class DownloadAsrModelRecoveryAction(RecoveryActionSchema):
    """Download the ASR models required to recover a missing-model failure."""

    id: Literal["download_asr_model"]
    label_key: Literal["download_asr_model"]
    description_key: Literal["download_asr_model"]
    enabled: bool
    disabled_reason: str | None
    method: Literal["POST"]
    endpoint: str
    payload: DownloadAsrModelRecoveryPayload
    confirmation_required: Literal[False]
    success_behavior: Literal["retry_stage_after_success"]


RecoveryAction: TypeAlias = Annotated[
    DownloadAsrModelRecoveryAction | RetryStageRecoveryAction,
    Field(discriminator="id"),
]


class TaskOverview(TaskListItem):
    """Complete workstation projection for one task."""

    pipeline_run_id: str | None
    stages: list[TaskStageOverview]
    execution_progress: ExecutionProgressOverview | None
    artifact_readiness: list[ArtifactReadinessOverview]
    artifacts: list[TaskArtifactOverview]
    safe_logs: list[SafeLogOverview]
    recovery_actions: list[RecoveryAction]
