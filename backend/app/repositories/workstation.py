"""Bounded SQL projections for the versioned workstation task APIs."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Final, assert_never
from urllib.parse import unquote, urlsplit

from pydantic import JsonValue, TypeAdapter, ValidationError
from sqlalchemy import and_, case, exists, func, or_, text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.api.schemas.workstation import (
    ArtifactReadinessOverview,
    ExecutionProgressOverview,
    RecoveryAction,
    SafeLogOverview,
    TaskArtifactOverview,
    TaskLibrarySummary,
    TaskListItem,
    TaskListPage,
    TaskListQuery,
    TaskOverview,
    TaskStageOverview,
)
from app.models import (
    Artifact,
    MediaSource,
    PipelineRun,
    StageRun,
    Task,
    TaskExecutionProgress,
    TaskStage,
    TaskTagLink,
)
from app.repositories.tasks import _redact_log_summary
from app.services.recovery_actions import serialize_recovery_actions, stage_display_label
from app.services.storage import build_artifact_content_path, summarize_stage_log


MAX_PAGE_SIZE: Final = 100
_LIKE_ESCAPE: Final = "\\"
_FILE_URI_IN_TEXT: Final = re.compile(
    r"file://(?:[^\s/\"'<>()[\]{},;!?]+)?/[^\s\"'<>()[\]{},;!?]+",
    re.IGNORECASE,
)
_HOST_PATH_IN_TEXT: Final = re.compile(
    r"(?<![:/\w])(?:/(?:[^\s\"'<>()[\]{},;!?]+)|[A-Za-z]:[\\/](?:[^\s\"'<>()[\]{},;!?]+)|\\\\(?:[^\s\"'<>()[\]{},;!?]+))"
)
_JSON_VALUE_ADAPTER: Final = TypeAdapter(JsonValue)
_RECOVERY_ACTION_ADAPTER: Final = TypeAdapter(RecoveryAction)
_EXPECTED_ARTIFACTS: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "ingest": ("source_video", ("source_video",)),
    "media_prep": ("prepared_audio", ("prepared_audio", "asr_audio")),
    "asr": ("transcript_json", ("transcript_json",)),
    "translation": ("translated_segments", ("translated_segments", "bilingual_transcript_json")),
    "highlight": ("highlight_candidates", ("highlight_candidates", "highlight_candidates_json")),
    "export": ("clip_video", ("clip_video", "exported_clip")),
    "report": ("report", ("report", "task_report_markdown")),
}


def list_workstation_tasks(session: Session, query: TaskListQuery) -> TaskListPage:
    """Return one SQL-filtered task-library page without materializing the library."""
    page_size = min(query.page_size, MAX_PAGE_SIZE)
    conditions = _list_conditions(session, query)
    count_statement = select(func.count()).select_from(
        select(Task.id).outerjoin(MediaSource, MediaSource.task_id == Task.id).where(*conditions).subquery()
    )
    total = int(session.exec(count_statement).one())
    ordering = _task_ordering(query)
    rows = session.exec(
        select(Task, MediaSource)
        .outerjoin(MediaSource, MediaSource.task_id == Task.id)
        .where(*conditions)
        .order_by(*ordering)
        .offset((query.page - 1) * page_size)
        .limit(page_size)
    ).all()
    task_ids = [task.id for task, _ in rows]
    tags_by_task = _tags_by_task(session, task_ids)
    stages_by_task = _legacy_stages_by_task(session, task_ids)
    progress_by_task = _progress_by_task(session, task_ids)
    items = [
        _task_list_item(task, source, tags_by_task[task.id], stages_by_task[task.id], progress_by_task.get(task.id))
        for task, source in rows
    ]
    page_count = (total + page_size - 1) // page_size
    return TaskListPage(
        items=items,
        page=query.page,
        page_size=page_size,
        total=total,
        page_count=page_count,
    )


def get_task_library_summary(session: Session) -> TaskLibrarySummary:
    """Count dashboard buckets in one SQL aggregation over the task table."""
    visible = Task.archived_at.is_(None)
    row = session.exec(
        select(
            func.coalesce(func.sum(case((and_(visible, Task.status == "running"), 1), else_=0)), 0),
            func.coalesce(func.sum(case((and_(visible, Task.status == "pending"), 1), else_=0)), 0),
            func.coalesce(func.sum(case((and_(visible, Task.status == "success"), 1), else_=0)), 0),
            func.coalesce(func.sum(case((and_(visible, Task.status == "failed"), 1), else_=0)), 0),
            func.coalesce(func.sum(case((Task.archived_at.is_not(None), 1), else_=0)), 0),
            func.coalesce(func.sum(Task.storage_bytes), 0),
        )
    ).one()
    return TaskLibrarySummary(
        active=int(row[0]),
        queued=int(row[1]),
        review_required=int(row[2]),
        failed=int(row[3]),
        archived=int(row[4]),
        storage_bytes=int(row[5]),
    )


def get_workstation_task_overview(session: Session, task_id: str) -> TaskOverview | None:
    """Project a single task with safe, UI-ready pipeline and artifact details."""
    task = session.get(Task, task_id)
    if task is None:
        return None
    source = session.exec(select(MediaSource).where(MediaSource.task_id == task_id)).first()
    tags = _tags_by_task(session, [task_id])[task_id]
    pipeline_run = session.exec(
        select(PipelineRun)
        .where(PipelineRun.task_id == task_id)
        .where(or_(PipelineRun.status == "pending", PipelineRun.started_at.is_not(None)))
        .order_by(case((PipelineRun.status == "pending", 0), else_=1), PipelineRun.created_at.desc(), PipelineRun.id.desc())
    ).first()
    legacy_stages = session.exec(
        select(TaskStage).where(TaskStage.task_id == task_id).order_by(TaskStage.id)
    ).all()
    planned = pipeline_run is None
    stage_records = _stage_records(session, pipeline_run, legacy_stages, planned=planned)
    artifacts = session.exec(select(Artifact).where(Artifact.task_id == task_id).order_by(Artifact.id)).all()
    execution_progress = session.get(TaskExecutionProgress, task_id)
    item = _task_list_item(task, source, tags, legacy_stages, execution_progress)
    return TaskOverview(
        **item.model_dump(),
        highlight_filtering_enabled=task.highlight_filtering_enabled,
        pipeline_run_id=pipeline_run.id if pipeline_run is not None else None,
        stages=stage_records,
        execution_progress=_execution_progress(execution_progress),
        artifact_readiness=_artifact_readiness(stage_records, artifacts),
        artifacts=_artifacts(artifacts),
        safe_logs=_safe_logs(task_id, stage_records),
        recovery_actions=_recovery_actions(task_id, task.status, legacy_stages),
    )


def _list_conditions(session: Session, query: TaskListQuery) -> list[object]:
    conditions: list[object] = []
    if not query.include_archived:
        conditions.append(Task.archived_at.is_(None))
    if query.statuses:
        conditions.append(Task.status.in_(query.statuses))
    if query.source_kind is not None:
        conditions.append(MediaSource.kind == query.source_kind)
    if query.tag is not None:
        conditions.append(
            exists(select(TaskTagLink.task_id).where(TaskTagLink.task_id == Task.id).where(TaskTagLink.tag_name == query.tag))
        )
    if query.updated_from is not None:
        conditions.append(Task.updated_at >= query.updated_from)
    if query.updated_to is not None:
        conditions.append(Task.updated_at <= query.updated_to)
    if query.readiness is not None:
        conditions.append(_readiness_condition(query.readiness))
    if query.query:
        conditions.append(_search_condition(session, query.query))
    return conditions


def _readiness_condition(readiness: str) -> object:
    """Filter by the persisted stage/artifact readiness signal used by the library."""
    expected_stage_names = tuple(_EXPECTED_ARTIFACTS)
    artifact_matches_own_stage = or_(
        *(
            and_(Artifact.stage_name == stage_name, Artifact.kind.in_(stored_kinds))
            for stage_name, (_, stored_kinds) in _EXPECTED_ARTIFACTS.items()
        )
    )
    artifact_matches_current_stage = or_(
        *(
            and_(TaskStage.name == stage_name, Artifact.kind.in_(stored_kinds))
            for stage_name, (_, stored_kinds) in _EXPECTED_ARTIFACTS.items()
        )
    )
    artifact_path_exists = func.artifact_path_exists(Artifact.path) == 1
    ready_artifact = exists(
        select(Artifact.id)
        .where(Artifact.task_id == Task.id)
        .where(artifact_matches_own_stage)
        .where(artifact_path_exists)
    )
    failed_stage = exists(
        select(TaskStage.id).where(TaskStage.task_id == Task.id).where(TaskStage.status == "failed")
    )
    missing_artifact = exists(
        select(TaskStage.id)
        .where(TaskStage.task_id == Task.id)
        .where(TaskStage.name.in_(expected_stage_names))
        .where(TaskStage.status == "success")
        .where(
            ~exists(
                select(Artifact.id)
                .where(Artifact.task_id == Task.id)
                .where(Artifact.stage_name == TaskStage.name)
                .where(artifact_matches_current_stage)
                .where(artifact_path_exists)
            )
        )
    )
    not_ready_stage = exists(
        select(TaskStage.id)
        .where(TaskStage.task_id == Task.id)
        .where(TaskStage.name.in_(expected_stage_names))
        .where(TaskStage.status.not_in(("success", "failed", "skipped")))
    )
    skipped_highlight_stage = exists(
        select(TaskStage.id)
        .where(TaskStage.task_id == Task.id)
        .where(TaskStage.name == "highlight")
        .where(TaskStage.status == "skipped")
    )
    match readiness:
        case "ready":
            return ready_artifact
        case "missing":
            return missing_artifact
        case "failed":
            return failed_stage
        case "not_ready":
            return not_ready_stage
        case "not_applicable":
            return skipped_highlight_stage
        case unreachable:
            assert_never(unreachable)


def _search_condition(session: Session, query: str) -> object:
    """Use migrated SQLite FTS when present, otherwise perform an escaped LIKE search."""
    if _sqlite_fts_available(session):
        escaped_fts_query = query.replace('"', '""')
        return Task.id.in_(text("SELECT task_id FROM task_search WHERE task_search MATCH :search").bindparams(search=f'"{escaped_fts_query}"'))
    like_pattern = f"%{_escape_like(query)}%"
    return or_(
        Task.title.ilike(like_pattern, escape=_LIKE_ESCAPE),
        Task.source_url.ilike(like_pattern, escape=_LIKE_ESCAPE),
        MediaSource.locator.ilike(like_pattern, escape=_LIKE_ESCAPE),
        MediaSource.display_name.ilike(like_pattern, escape=_LIKE_ESCAPE),
    )


def _sqlite_fts_available(session: Session) -> bool:
    try:
        session.exec(text("SELECT 1 FROM task_search LIMIT 1")).first()
    except OperationalError:
        return False
    return True


def _escape_like(value: str) -> str:
    """Escape a user string for a LIKE expression using a fixed escape character."""
    return value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", f"{_LIKE_ESCAPE}%").replace("_", f"{_LIKE_ESCAPE}_")


def _task_ordering(query: TaskListQuery) -> tuple[object, object]:
    match query.sort:
        case "updated_at":
            column = Task.updated_at
        case "created_at":
            column = Task.created_at
        case "title":
            column = Task.title
        case "storage_bytes":
            column = Task.storage_bytes
    match query.direction:
        case "asc":
            return column.asc(), Task.id.asc()
        case "desc":
            return column.desc(), Task.id.desc()


def _tags_by_task(session: Session, task_ids: Sequence[str]) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = defaultdict(list)
    if not task_ids:
        return tags
    rows = session.exec(
        select(TaskTagLink.task_id, TaskTagLink.tag_name)
        .where(TaskTagLink.task_id.in_(task_ids))
        .order_by(TaskTagLink.task_id, TaskTagLink.tag_name)
    ).all()
    for task_id, tag_name in rows:
        tags[task_id].append(tag_name)
    return tags


def _legacy_stages_by_task(session: Session, task_ids: Sequence[str]) -> dict[str, list[TaskStage]]:
    stages: dict[str, list[TaskStage]] = defaultdict(list)
    if not task_ids:
        return stages
    rows = session.exec(
        select(TaskStage).where(TaskStage.task_id.in_(task_ids)).order_by(TaskStage.task_id, TaskStage.id)
    ).all()
    for stage in rows:
        stages[stage.task_id].append(stage)
    return stages


def _progress_by_task(session: Session, task_ids: Sequence[str]) -> dict[str, TaskExecutionProgress]:
    if not task_ids:
        return {}
    rows = session.exec(select(TaskExecutionProgress).where(TaskExecutionProgress.task_id.in_(task_ids))).all()
    return {progress.task_id: progress for progress in rows}


def _task_list_item(
    task: Task,
    source: MediaSource | None,
    tags: list[str],
    stages: Sequence[TaskStage],
    execution_progress: TaskExecutionProgress | None,
) -> TaskListItem:
    return TaskListItem(
        task_id=task.id,
        title=task.title or task.source_video_id or task.id,
        source_kind=source.kind if source is not None else "unknown",
        source_label=_source_label(source),
        status=task.status,
        current_stage=_current_stage(stages),
        progress_percent=_progress_percent(stages, execution_progress),
        tags=tags,
        storage_bytes=task.storage_bytes,
        created_at=task.created_at,
        updated_at=task.updated_at,
        archived_at=task.archived_at,
    )


def _source_label(source: MediaSource | None) -> str:
    """Return a useful v2 source label without serializing a host locator."""
    if source is None:
        return "Source"
    if source.display_name:
        if source.display_name.casefold().startswith("file:"):
            return _local_source_label(source.display_name, source.kind)
        return _sanitize_visible_text(source.display_name) or _generic_source_label(source.kind)
    if _is_local_or_file_source(source):
        return _local_source_label(source.locator, source.kind)
    return _generic_source_label(source.kind)


def _is_local_or_file_source(source: MediaSource) -> bool:
    match source.kind:
        case "local":
            return True
        case _:
            return source.locator.casefold().startswith("file:")


def _local_source_basename(locator: str) -> str | None:
    """Extract a cross-platform file basename without retaining its parent path."""
    path = unquote(urlsplit(locator).path) if locator.casefold().startswith("file:") else locator
    basename = re.split(r"[\\/]", path.rstrip("\\/"))[-1]
    return basename or None


def _local_source_label(locator: str, source_kind: str) -> str:
    """Project a local/file locator as its basename or a safe generic label."""
    basename = _local_source_basename(locator)
    if basename:
        return _sanitize_visible_text(basename) or _generic_source_label(source_kind)
    return _generic_source_label(source_kind)


def _generic_source_label(source_kind: str) -> str:
    match source_kind:
        case "local":
            return "Local source"
        case "bilibili":
            return "Bilibili source"
        case _:
            return "Source"


def _current_stage(stages: Sequence[TaskStage]) -> str | None:
    for stage in stages:
        if stage.status == "running":
            return stage.name
    for stage in stages:
        if stage.status in {"pending", "failed", "cancelled"}:
            return stage.name
    return None


def _progress_percent(stages: Sequence[TaskStage], progress: TaskExecutionProgress | None) -> int:
    if not stages:
        return 0
    completed = sum(stage.status in {"success", "skipped"} for stage in stages)
    in_progress = 0.0
    if progress is not None and progress.phase_count > 0:
        in_progress = min(max(progress.phase_index / progress.phase_count, 0.0), 1.0)
    return min(100, round(((completed + in_progress) / len(stages)) * 100))


def _stage_records(
    session: Session,
    pipeline_run: PipelineRun | None,
    legacy_stages: Sequence[TaskStage],
    *,
    planned: bool,
) -> list[TaskStageOverview]:
    stages: Sequence[StageRun | TaskStage] = legacy_stages
    if pipeline_run is not None:
        run_stages = session.exec(select(StageRun).where(StageRun.run_id == pipeline_run.id).order_by(StageRun.id)).all()
        if run_stages:
            stages = run_stages
    return [
        TaskStageOverview(
            name=stage.name,
            status="planned" if planned else stage.status,
            summary=_sanitize_visible_text(stage.summary),
            failure_code=stage.failure_code,
            attempts=stage.attempts,
            started_at=stage.started_at,
            finished_at=stage.finished_at,
            planned=planned,
        )
        for stage in stages
    ]


def _execution_progress(progress: TaskExecutionProgress | None) -> ExecutionProgressOverview | None:
    if progress is None:
        return None
    try:
        decoded = _JSON_VALUE_ADAPTER.validate_json(progress.phase_timings_json)
    except ValidationError:
        phases: list[dict[str, JsonValue]] = []
    else:
        sanitized = _redact_absolute_paths(decoded)
        match sanitized:
            case list():
                phases = [item for item in sanitized if isinstance(item, dict)]
            case _:
                phases = []
    return ExecutionProgressOverview(
        stage_name=progress.stage_name,
        current_phase=progress.current_phase,
        phase_index=progress.phase_index,
        phase_count=progress.phase_count,
        latest_message=_sanitize_visible_text(progress.latest_message),
        phase_started_at=progress.phase_started_at,
        heartbeat_at=progress.heartbeat_at,
        phases=phases,
    )


def _artifact_readiness(stages: Sequence[TaskStageOverview], artifacts: Sequence[Artifact]) -> list[ArtifactReadinessOverview]:
    by_stage_kind = {(artifact.stage_name, artifact.kind): artifact for artifact in artifacts}
    readiness: list[ArtifactReadinessOverview] = []
    for stage in stages:
        expected = _EXPECTED_ARTIFACTS.get(stage.name)
        if expected is None:
            continue
        public_kind, stored_kinds = expected
        artifact = next((by_stage_kind.get((stage.name, kind)) for kind in stored_kinds if (stage.name, kind) in by_stage_kind), None)
        artifact_id = artifact.id if artifact is not None else None
        if artifact is not None and Path(artifact.path).exists():
            status = "ready"
        elif stage.name == "highlight" and stage.status == "skipped":
            status = "not_applicable"
        elif stage.status == "failed":
            status = "failed"
        elif stage.status == "success":
            status = "missing"
        else:
            status = "not_ready"
        readiness.append(
            ArtifactReadinessOverview(
                stage_name=stage.name,
                kind=public_kind,
                status=status,
                artifact_id=artifact_id,
                path=build_artifact_content_path(task_id=artifact.task_id, artifact_id=artifact_id, artifact_path=artifact.path)
                if artifact is not None and artifact_id is not None
                else None,
            )
        )
        if stage.status == "failed":
            break
    return readiness


def _artifacts(artifacts: Sequence[Artifact]) -> list[TaskArtifactOverview]:
    return [
        TaskArtifactOverview(
            artifact_id=artifact.id,
            stage_name=artifact.stage_name,
            kind=artifact.kind,
            path=build_artifact_content_path(task_id=artifact.task_id, artifact_id=artifact.id, artifact_path=artifact.path),
            metadata_json=_sanitize_artifact_metadata(artifact.metadata_json),
            created_at=artifact.created_at,
        )
        for artifact in artifacts
        if artifact.id is not None
    ]


def _sanitize_artifact_metadata(metadata_json: str) -> str:
    """Serialize metadata without disclosing absolute host paths at the v2 boundary."""
    try:
        metadata = _JSON_VALUE_ADAPTER.validate_json(metadata_json)
    except ValidationError:
        return "{}"
    return json.dumps(_redact_absolute_paths(metadata), separators=(",", ":"), sort_keys=True)


def _redact_absolute_paths(value: JsonValue) -> JsonValue:
    """Recursively preserve JSON structure while replacing absolute path strings."""
    match value:
        case str():
            return _sanitize_visible_text(value)
        case list():
            return [_redact_absolute_paths(item) for item in value]
        case dict():
            return {key: _redact_absolute_paths(item) for key, item in value.items()}
        case bool() | int() | float() | None:
            return value
        case unreachable:
            assert_never(unreachable)


def _sanitize_visible_text(value: str | None) -> str | None:
    """Redact cross-platform absolute host paths while preserving surrounding diagnostics."""
    if value is None:
        return None
    normalized_file_uris = _FILE_URI_IN_TEXT.sub(_normalize_file_uri, value)
    return _HOST_PATH_IN_TEXT.sub("[path]", normalized_file_uris)


def _normalize_file_uri(match: re.Match[str]) -> str:
    """Replace a file URI with its decoded basename without retaining its host path."""
    return _local_source_basename(match.group()) or "[path]"


def _recovery_actions(
    task_id: str,
    task_status: str,
    stages: list[TaskStage],
) -> list[RecoveryAction]:
    """Validate backend-authored actions against their exact discriminated contracts."""
    return [
        _RECOVERY_ACTION_ADAPTER.validate_python(action)
        for action in serialize_recovery_actions(task_id=task_id, task_status=task_status, stages=stages)
    ]


def _safe_logs(task_id: str, stages: Sequence[TaskStageOverview]) -> list[SafeLogOverview]:
    return [
        SafeLogOverview(
            stage_name=stage.name,
            status=stage.status,
            summary=_sanitize_visible_text(
                _redact_log_summary(summarize_stage_log(task_id, stage.name) or stage.summary)
            ),
            display_label=stage_display_label(stage.name),
        )
        for stage in stages
    ]
