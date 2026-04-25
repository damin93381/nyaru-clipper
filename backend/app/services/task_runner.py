from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlmodel import Session, select

from app.models import CANONICAL_STAGES, Task, TaskJob, TaskStage, utc_now
from app.repositories.tasks import get_task_record
from app.services.asr_whisperx import transcribe_task_audio
from app.services.downloader import download_bilibili_vod
from app.services.highlights import analyze_task_highlights
from app.services.media_prep import prepare_media_for_asr
from app.services.pipeline_support import append_stage_log
from app.services.reporting import generate_task_report
from app.services.storage import ensure_task_dirs, log_file_for_stage
from app.services.translation_provider import translate_task_subtitles

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
            candidate = Path(artifact.path)
            if candidate.exists():
                return candidate

    raw_files = sorted(path for path in task_dirs["raw"].glob("source.*") if path.is_file())
    if raw_files:
        return raw_files[0]
    raise FileNotFoundError("Source video artifact is missing for media preparation")


def _execute_media_prep(session: Session, task_id: str):
    return prepare_media_for_asr(session, task_id, _resolve_ingest_video_path(task_id, session))


def _execute_export(session: Session, task_id: str) -> StageDirective:
    return StageDirective(status="skipped", summary="Awaiting user-confirmed clip export")


STAGE_EXECUTORS: dict[str, StageExecutor] = {
    "ingest": _execute_ingest,
    "media_prep": _execute_media_prep,
    "asr": transcribe_task_audio,
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
) -> TaskRunResult:
    task = session.get(Task, task_id)
    if task is None:
        raise ValueError(f"Unknown task_id: {task_id}")
    job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
    if job is None:
        raise ValueError(f"Task job not found for task_id: {task_id}")

    stages = _load_stage_map(session, task_id)
    first_stage_name = start_stage_name or job.stage_name or _first_incomplete_stage_name(stages)
    if first_stage_name not in CANONICAL_STAGE_ORDER:
        raise ValueError(f"Unknown stage: {first_stage_name}")

    completed_stages: list[str] = []
    start_index = CANONICAL_STAGE_ORDER.index(first_stage_name)
    for index in range(start_index, len(CANONICAL_STAGE_ORDER)):
        stage_name = CANONICAL_STAGE_ORDER[index]
        stage = stages[stage_name]
        log_path = log_file_for_stage(task_id, stage_name)

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
            session.commit()
            stages = _load_stage_map(session, task_id)
            stage = stages[stage_name]

        append_stage_log(log_path, f"task_runner:start stage={stage_name}")

        try:
            outcome = STAGE_EXECUTORS[stage_name](session, task_id)
        except Exception as exc:
            append_stage_log(log_path, f"task_runner:error {exc}")
            _mark_stage_failed(task=task, job=job, stage=stage, summary=str(exc) or exc.__class__.__name__)
            session.add(task)
            session.add(job)
            session.add(stage)
            session.commit()
            raise

        directive = outcome if isinstance(outcome, StageDirective) else None
        if directive is not None:
            _apply_stage_directive(stage=stage, directive=directive)
        elif stage.status not in {"success", "skipped"}:
            _mark_stage_success(stage, summary=f"Completed {stage_name}")

        _advance_job_checkpoint(job=job, next_stage_name=_next_stage_name(index))
        task.status = "running" if index < len(CANONICAL_STAGE_ORDER) - 1 else "success"
        task.updated_at = utc_now()
        session.add(task)
        session.add(job)
        session.add(stage)
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
        session.commit()

    return TaskRunResult(task_id=task_id, final_status=task.status, completed_stages=completed_stages)


def _load_stage_map(session: Session, task_id: str) -> dict[str, TaskStage]:
    return {
        stage.name: stage
        for stage in session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
    }


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
    stage.started_at = now
    stage.finished_at = None
    stage.attempts += 1
    stage.updated_at = now


def _mark_stage_success(stage: TaskStage, *, summary: str) -> None:
    now = utc_now()
    stage.status = "success"
    stage.summary = summary
    stage.finished_at = now
    stage.updated_at = now


def _mark_stage_failed(*, task: Task, job: TaskJob, stage: TaskStage, summary: str) -> None:
    now = utc_now()
    task.status = "failed"
    task.updated_at = now
    job.status = "failed"
    job.stage_name = stage.name
    job.finished_at = now
    job.updated_at = now
    stage.status = "failed"
    stage.summary = summary
    stage.finished_at = now
    stage.updated_at = now


def _apply_stage_directive(*, stage: TaskStage, directive: StageDirective) -> None:
    now = utc_now()
    stage.status = directive.status
    stage.summary = directive.summary
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
