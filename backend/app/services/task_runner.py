from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlmodel import Session, select

from app.models import CANONICAL_STAGES, MediaSource, Task, TaskJob, TaskStage, utc_now
from app.repositories.tasks import clear_task_execution_progress, get_task_record, upsert_task_execution_progress
from app.services.asr_child_runner import build_asr_child_command
from app.services.asr_whisperx import (
    ASR_PIPELINE_PHASES,
    ASR_STAGE_SUCCESS_SUMMARY,
    AsrFailure,
    load_asr_result_manifest,
    publish_asr_artifacts_from_manifest,
)
from app.services.failure_codes import failure_code_from_exception
from app.services.downloader import download_bilibili_vod
from app.services.highlights import analyze_task_highlights
from app.services.media_prep import prepare_media_for_asr
from app.services.pipeline_support import append_stage_log, run_tracked_structured_process_group_command
from app.services.reporting import generate_task_report
from app.services.source_catalog import resolve_local_reference_artifact, resolve_persisted_local_media_source
from app.services.storage import ensure_task_dirs, log_file_for_stage, persist_artifact_metadata
from app.services.task_control import (
    StaleExecutionTokenError,
    bind_execution_context,
    clear_execution_context,
    ensure_current_execution_context,
    finalize_execution,
    finalize_cancelled,
    get_control_requests,
    get_execution_context,
)
from app.services.translation_provider import translate_task_subtitles
from app.services.workstation_runs import (
    create_pipeline_run,
    finish_pipeline_run,
    get_pending_pipeline_run,
    start_pipeline_run,
    sync_stage_run,
)

CANONICAL_STAGE_ORDER = CANONICAL_STAGES


@dataclass(slots=True)
class StageDirective:
    status: str
    summary: str


@dataclass(slots=True)
class TaskRunResult:
    task_id: str
    final_status: str
    completed_stages: list[str]


StageExecutor = Callable[[Session, str], Any]


def _execute_ingest(session: Session, task_id: str):
    media_source = session.exec(select(MediaSource).where(MediaSource.task_id == task_id)).first()
    if media_source is not None and media_source.kind == "local" and media_source.import_mode == "reference":
        local_source = resolve_persisted_local_media_source(media_source.metadata_json)
        reference_path = ensure_task_dirs(task_id)["raw"] / "local-reference.json"
        reference_path.write_text(
            media_source.metadata_json,
            encoding="utf-8",
        )
        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="ingest",
            kind="source_video",
            path=reference_path,
            metadata={
                "import_mode": "reference",
                "relative_path": local_source.relative_path,
                "root_id": local_source.root_id,
            },
        )
        from app.services.pipeline_support import set_stage_status

        set_stage_status(
            session,
            task_id=task_id,
            stage_name="ingest",
            status="success",
            summary="Referenced local source video",
        )
        return local_source

    result = download_bilibili_vod(session, task_id)
    source_video_id = str(result.source_metadata.get("source_video_id") or "").strip() or None
    if source_video_id:
        task = session.get(Task, task_id)
        if task is not None and task.source_video_id != source_video_id:
            task.source_video_id = source_video_id
            task.updated_at = utc_now()
            session.add(task)
    return result


def _resolve_ingest_video_path(task_id: str, session: Session) -> Path:
    record = get_task_record(session, task_id)
    if record is None:
        raise ValueError(f"Unknown task_id: {task_id}")

    task_dirs = ensure_task_dirs(task_id)
    preferred = task_dirs["raw"] / "source.mp4"
    if preferred.exists():
        return preferred

    for artifact in reversed(record.artifacts):
        if artifact.stage_name == "ingest" and artifact.kind == "source_video":
            local_source = resolve_local_reference_artifact(artifact.metadata_json)
            if local_source is not None:
                return local_source.path
            candidate = Path(artifact.path)
            if candidate.exists():
                return candidate

    raw_files = sorted(path for path in task_dirs["raw"].glob("source.*") if path.is_file())
    if raw_files:
        return raw_files[0]
    raise FileNotFoundError("Source video artifact is missing for media preparation")


def _execute_media_prep(session: Session, task_id: str):
    record = get_task_record(session, task_id)
    if record is None:
        raise ValueError(f"Unknown task_id: {task_id}")
    source_video_path = _resolve_ingest_video_path(task_id, session)
    source_locator = _local_source_locator(record)
    return prepare_media_for_asr(session, task_id, source_video_path, source_locator=source_locator)


def _local_source_locator(record) -> str | None:
    """Return an opaque locator for local references without exposing their resolved path."""
    for artifact in reversed(record.artifacts):
        if artifact.stage_name != "ingest" or artifact.kind != "source_video":
            continue
        local_source = resolve_local_reference_artifact(artifact.metadata_json)
        if local_source is not None:
            return local_source.locator
    return None


@dataclass
class _AsrExecutionProgressTracker:
    session: Session
    task_id: str

    def __post_init__(self) -> None:
        self._phase_timings = [
            {"name": phase, "status": "pending", "elapsed_ms": None} for phase in ASR_PIPELINE_PHASES
        ]
        self._current_phase = ASR_PIPELINE_PHASES[0]
        self._latest_message: str | None = None
        self._phase_started_at: datetime | None = None
        self._heartbeat_at: datetime | None = None

    def handle_event(self, event: dict[str, Any]) -> None:
        event_name = str(event.get("event") or "").strip()
        phase = str(event.get("phase") or self._current_phase).strip() or self._current_phase
        phase_index = _coerce_phase_index(event.get("phase_index"), phase=phase)
        phase_count = _coerce_phase_count(event.get("phase_count"))
        event_time = _parse_event_timestamp(event.get("ts")) or utc_now()

        if event_name == "phase_start":
            self._current_phase = phase
            self._phase_started_at = event_time
            self._heartbeat_at = event_time
            self._latest_message = _coerce_message(event.get("message"))
            _set_phase_state(self._phase_timings, phase=phase, status="running", elapsed_ms=None)
        elif event_name == "heartbeat":
            self._current_phase = phase
            self._heartbeat_at = event_time
            self._latest_message = _coerce_message(event.get("message"))
            _set_phase_state(
                self._phase_timings,
                phase=phase,
                status="running",
                elapsed_ms=_coerce_elapsed_ms(event.get("elapsed_ms")),
            )
        elif event_name == "phase_complete":
            self._current_phase = phase
            self._heartbeat_at = event_time
            _set_phase_state(
                self._phase_timings,
                phase=phase,
                status="success",
                elapsed_ms=_coerce_elapsed_ms(event.get("elapsed_ms")),
            )
        elif event_name == "failure":
            self._current_phase = phase
            self._heartbeat_at = event_time
            self._latest_message = _coerce_message(event.get("message"))
            _set_phase_state(self._phase_timings, phase=phase, status="failed", elapsed_ms=None)
        elif event_name == "success":
            self._current_phase = phase
            self._heartbeat_at = event_time
            _set_phase_state(
                self._phase_timings,
                phase=phase,
                status="success",
                elapsed_ms=_coerce_elapsed_ms(event.get("elapsed_ms_total")),
            )
        else:
            return

        upsert_task_execution_progress(
            self.session,
            task_id=self.task_id,
            stage_name="asr",
            current_phase=self._current_phase,
            phase_index=phase_index,
            phase_count=phase_count,
            latest_message=self._latest_message,
            phase_started_at=self._phase_started_at,
            heartbeat_at=self._heartbeat_at,
            phase_timings=self._phase_timings,
        )
        self.session.commit()


def _execute_asr_subprocess(session: Session, task_id: str) -> StageDirective:
    record = get_task_record(session, task_id)
    if record is None:
        raise ValueError(f"Unknown task_id: {task_id}")

    log_path = log_file_for_stage(task_id, "asr")
    progress_tracker = _AsrExecutionProgressTracker(session=session, task_id=task_id)
    clear_task_execution_progress(session, task_id=task_id)
    session.commit()

    try:
        process_result = run_tracked_structured_process_group_command(
            session,
            task_id=task_id,
            args=build_asr_child_command(task_id),
            log_path=log_path,
            on_event=progress_tracker.handle_event,
        )
        success_event = _resolve_success_event(process_result.events)
        if process_result.completed_process.returncode != 0:
            raise _resolve_child_failure(task_id=task_id, events=process_result.events)
        if success_event is None:
            raise AsrFailure(
                code="asr_child_failed",
                message="ASR child exited without emitting a terminal success event.",
            )
        manifest_path = _resolve_success_manifest_path(success_event)
        _ensure_current_execution_context_if_bound(session, task_id=task_id)
        manifest = load_asr_result_manifest(manifest_path)
        publish_asr_artifacts_from_manifest(session, task_id=task_id, manifest=manifest)
        _ensure_current_execution_context_if_bound(session, task_id=task_id)
        session.commit()
        return StageDirective(status="success", summary=ASR_STAGE_SUCCESS_SUMMARY)
    finally:
        clear_task_execution_progress(session, task_id=task_id)
        session.commit()


def _execute_export(session: Session, task_id: str) -> StageDirective:
    return StageDirective(status="skipped", summary="Awaiting user-confirmed clip export")


STAGE_EXECUTORS: dict[str, StageExecutor] = {
    "ingest": _execute_ingest,
    "media_prep": _execute_media_prep,
    "asr": _execute_asr_subprocess,
    "translation": translate_task_subtitles,
    "highlight": analyze_task_highlights,
    "export": _execute_export,
    "report": generate_task_report,
}


def run_task_pipeline(
    session: Session,
    task_id: str,
    *,
    start_stage_name: str | None = None,
    claimed_stage_running: bool = False,
    execution_token: str | None = None,
) -> TaskRunResult:
    if execution_token is not None:
        bind_execution_context(session, task_id=task_id, execution_token=execution_token)

    try:
        task = session.get(Task, task_id)
        if task is None:
            raise ValueError(f"Unknown task_id: {task_id}")
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
        if job is None:
            raise ValueError(f"Task job not found for task_id: {task_id}")
        pipeline_run = get_pending_pipeline_run(session, task_id)
        if pipeline_run is None:
            pipeline_run = create_pipeline_run(session, task_id, "legacy")
        start_pipeline_run(session, pipeline_run)

        stages = _load_stage_map(session, task_id)
        first_stage_name = start_stage_name or job.stage_name or _first_incomplete_stage_name(stages)
        if first_stage_name not in CANONICAL_STAGE_ORDER:
            raise ValueError(f"Unknown stage: {first_stage_name}")

        completed_stages: list[str] = []
        start_index = CANONICAL_STAGE_ORDER.index(first_stage_name)

        try:
            _ensure_current_execution_context_if_bound(session, task_id=task_id)
            if _finalize_cancelled_if_requested(session, task_id=task_id):
                _sync_current_stage_run(session, pipeline_run.id, task_id)
                finish_pipeline_run(session, pipeline_run, "cancelled")
                return _current_run_result(session, task_id=task_id, completed_stages=completed_stages)

            for index in range(start_index, len(CANONICAL_STAGE_ORDER)):
                stage_name = CANONICAL_STAGE_ORDER[index]
                stage = stages[stage_name]
                log_path = log_file_for_stage(task_id, stage_name)

                _ensure_current_execution_context_if_bound(session, task_id=task_id)
                if _finalize_cancelled_if_requested(session, task_id=task_id):
                    _sync_current_stage_run(session, pipeline_run.id, task_id)
                    finish_pipeline_run(session, pipeline_run, "cancelled")
                    return _current_run_result(session, task_id=task_id, completed_stages=completed_stages)

                if index == start_index and claimed_stage_running:
                    _sync_running_claim(task=task, job=job, stage=stage)
                    session.add(task)
                    session.add(job)
                    session.add(stage)
                else:
                    _mark_stage_running(task=task, job=job, stage=stage)
                    session.add(task)
                    session.add(job)
                    session.add(stage)
                    sync_stage_run(session, pipeline_run.id, stage)
                    session.commit()
                    stages = _load_stage_map(session, task_id)
                    stage = stages[stage_name]

                sync_stage_run(session, pipeline_run.id, stage)

                append_stage_log(log_path, f"task_runner:start stage={stage_name}")

                try:
                    outcome = STAGE_EXECUTORS[stage_name](session, task_id)
                    _ensure_current_execution_context_if_bound(session, task_id=task_id)
                except StaleExecutionTokenError:
                    session.rollback()
                    return _current_run_result(session, task_id=task_id, completed_stages=completed_stages)
                except Exception as exc:
                    append_stage_log(log_path, f"task_runner:error {exc}")
                    _mark_stage_failed(
                        task=task,
                        job=job,
                        stage=stage,
                        summary=_failure_summary(exc),
                        failure_code=failure_code_from_exception(stage_name, exc),
                    )
                    session.add(task)
                    session.add(job)
                    session.add(stage)
                    sync_stage_run(session, pipeline_run.id, stage)
                    finish_pipeline_run(session, pipeline_run, "failed")
                    session.commit()
                    raise

                directive = outcome if isinstance(outcome, StageDirective) else None
                if directive is not None:
                    _apply_stage_directive(stage=stage, directive=directive)
                elif stage.status not in {"success", "skipped"}:
                    _mark_stage_success(stage, summary=f"Completed {stage_name}")

                if _finalize_cancelled_if_requested(session, task_id=task_id):
                    sync_stage_run(session, pipeline_run.id, stage)
                    _sync_current_stage_run(session, pipeline_run.id, task_id)
                    finish_pipeline_run(session, pipeline_run, "cancelled")
                    session.commit()
                    completed_stages.append(stage_name)
                    append_stage_log(log_path, f"task_runner:complete stage={stage_name} status={stage.status}")
                    return _current_run_result(session, task_id=task_id, completed_stages=completed_stages)

                _advance_job_checkpoint(job=job, next_stage_name=_next_stage_name(index))
                task.status = "running" if index < len(CANONICAL_STAGE_ORDER) - 1 else "success"
                task.updated_at = utc_now()
                session.add(task)
                session.add(job)
                session.add(stage)
                sync_stage_run(session, pipeline_run.id, stage)
                session.commit()
                append_stage_log(log_path, f"task_runner:complete stage={stage_name} status={stage.status}")
                completed_stages.append(stage_name)
                stages = _load_stage_map(session, task_id)

            final_stage = stages[CANONICAL_STAGE_ORDER[-1]]
            if final_stage.status in {"success", "skipped"}:
                job.status = "success"
                job.stage_name = CANONICAL_STAGE_ORDER[-1]
                job.finished_at = utc_now()
                job.updated_at = job.finished_at
                task.status = "success"
                task.updated_at = job.finished_at
                session.add(job)
                session.add(task)
                finish_pipeline_run(session, pipeline_run, "success")
                session.commit()
        except StaleExecutionTokenError:
            session.rollback()
            return _current_run_result(session, task_id=task_id, completed_stages=completed_stages)

        return TaskRunResult(task_id=task_id, final_status=task.status, completed_stages=completed_stages)
    finally:
        if execution_token is not None:
            try:
                finalize_execution(session, task_id=task_id, execution_token=execution_token)
                session.commit()
            except (StaleExecutionTokenError, RuntimeError, ValueError):
                session.rollback()
            clear_execution_context(session)


def _load_stage_map(session: Session, task_id: str) -> dict[str, TaskStage]:
    return {
        stage.name: stage
        for stage in session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
    }


def _sync_current_stage_run(session: Session, run_id: str, task_id: str) -> None:
    job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
    if job is None:
        return
    stage = session.exec(
        select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == job.stage_name)
    ).first()
    if stage is not None:
        sync_stage_run(session, run_id, stage)


def _first_incomplete_stage_name(stages: dict[str, TaskStage]) -> str:
    for stage_name in CANONICAL_STAGE_ORDER:
        if stages[stage_name].status != "success":
            return stage_name
    return CANONICAL_STAGE_ORDER[-1]


def _sync_running_claim(*, task: Task, job: TaskJob, stage: TaskStage) -> None:
    now = utc_now()
    task.status = "running"
    task.updated_at = now
    job.status = "running"
    job.stage_name = stage.name
    job.updated_at = now
    stage.status = "running"
    stage.failure_code = None
    stage.started_at = stage.started_at or now
    stage.updated_at = now


def _mark_stage_running(*, task: Task, job: TaskJob, stage: TaskStage) -> None:
    now = utc_now()
    task.status = "running"
    task.updated_at = now
    job.status = "running"
    job.stage_name = stage.name
    job.started_at = job.started_at or now
    job.finished_at = None
    job.updated_at = now
    stage.status = "running"
    stage.failure_code = None
    stage.started_at = now
    stage.finished_at = None
    stage.attempts += 1
    stage.updated_at = now


def _mark_stage_success(stage: TaskStage, *, summary: str) -> None:
    now = utc_now()
    stage.status = "success"
    stage.summary = summary
    stage.failure_code = None
    stage.finished_at = now
    stage.updated_at = now


def _mark_stage_failed(*, task: Task, job: TaskJob, stage: TaskStage, summary: str, failure_code: str) -> None:
    now = utc_now()
    task.status = "failed"
    task.updated_at = now
    job.status = "failed"
    job.stage_name = stage.name
    job.finished_at = now
    job.updated_at = now
    stage.status = "failed"
    stage.summary = summary
    stage.failure_code = failure_code
    stage.finished_at = now
    stage.updated_at = now


def _apply_stage_directive(*, stage: TaskStage, directive: StageDirective) -> None:
    now = utc_now()
    stage.status = directive.status
    stage.summary = directive.summary
    if directive.status in {"success", "skipped", "pending", "running"}:
        stage.failure_code = None
    stage.finished_at = now
    stage.updated_at = now


def _advance_job_checkpoint(*, job: TaskJob, next_stage_name: str | None) -> None:
    now = utc_now()
    job.updated_at = now
    if next_stage_name is None:
        job.stage_name = CANONICAL_STAGE_ORDER[-1]
    else:
        job.stage_name = next_stage_name


def _next_stage_name(index: int) -> str | None:
    next_index = index + 1
    if next_index >= len(CANONICAL_STAGE_ORDER):
        return None
    return CANONICAL_STAGE_ORDER[next_index]


def _coerce_phase_index(value: Any, *, phase: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = ASR_PIPELINE_PHASES.index(phase) + 1 if phase in ASR_PIPELINE_PHASES else 1
    return max(1, parsed)


def _coerce_phase_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = len(ASR_PIPELINE_PHASES)
    return max(1, parsed)


def _coerce_elapsed_ms(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _coerce_message(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _set_phase_state(
    phases: list[dict[str, Any]],
    *,
    phase: str,
    status: str,
    elapsed_ms: int | None,
) -> None:
    for item in phases:
        if item.get("name") != phase:
            continue
        item["status"] = status
        item["elapsed_ms"] = elapsed_ms
        return


def _parse_event_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_success_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event") == "success":
            return event
    return None


def _resolve_success_manifest_path(success_event: dict[str, Any]) -> Path:
    manifest_path = success_event.get("manifest_path")
    if not isinstance(manifest_path, str) or not manifest_path.strip():
        raise AsrFailure(
            code="asr_child_failed",
            message="ASR child success event did not include a manifest path.",
        )
    return Path(manifest_path)


def _resolve_child_failure(*, task_id: str, events: list[dict[str, Any]]) -> AsrFailure:
    for event in reversed(events):
        if event.get("event") == "failure":
            code = str(event.get("code") or "asr_child_failed").strip() or "asr_child_failed"
            message = str(event.get("message") or "ASR child reported failure.").strip() or "ASR child reported failure."
            return AsrFailure(code=code, message=message)

    manifest_path = ensure_task_dirs(task_id)["work"] / "asr-result.json"
    if manifest_path.exists():
        manifest = load_asr_result_manifest(manifest_path)
        if manifest.status != "success":
            error = manifest.error or {}
            return AsrFailure(
                code=str(error.get("code") or "asr_child_failed"),
                message=str(error.get("message") or "ASR child reported failure."),
            )
    return AsrFailure(
        code="asr_child_failed",
        message=f"ASR child exited unsuccessfully for task {task_id}.",
    )


def _failure_summary(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.strip():
        return code.strip()
    return str(exc) or exc.__class__.__name__


def _ensure_current_execution_context_if_bound(session: Session, *, task_id: str) -> None:
    context = get_execution_context(session)
    if context is None:
        return
    ensure_current_execution_context(session, task_id=task_id)


def _finalize_cancelled_if_requested(session: Session, *, task_id: str) -> bool:
    context = get_execution_context(session)
    if context is None:
        return False
    ensure_current_execution_context(session, task_id=task_id)
    requests = get_control_requests(session, task_id=task_id)
    if not (requests.cancel_requested or requests.force_kill_requested):
        return False
    control_token = context.get("execution_token")
    if not isinstance(control_token, str):
        return False
    finalize_cancelled(session, task_id=task_id, execution_token=control_token)
    return True


def _current_run_result(session: Session, *, task_id: str, completed_stages: list[str]) -> TaskRunResult:
    task = session.get(Task, task_id)
    final_status = task.status if task is not None else "pending"
    return TaskRunResult(
        task_id=task_id,
        final_status=final_status,
        completed_stages=list(completed_stages),
    )
