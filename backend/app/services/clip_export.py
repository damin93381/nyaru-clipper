from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from app.models import Artifact, ClipCandidate
from app.repositories.tasks import get_task_record
from app.services.pipeline_support import run_logged_command, set_stage_status
from app.services.storage import ensure_task_dirs, log_file_for_stage, persist_artifact_metadata
from app.settings import get_settings


@dataclass(slots=True)
class ClipExportResult:
    task_id: str
    candidate_id: int
    start_s: float
    end_s: float
    output_path: Path
    artifact_id: int


class ClipExportFailure(RuntimeError):
    def __init__(self, *, code: str, message: str):
        super().__init__(message)
        self.code = code


def export_confirmed_clip(
    session: Session,
    task_id: str,
    *,
    candidate_id: int,
    start_s: float | None = None,
    end_s: float | None = None,
) -> ClipExportResult:
    record = get_task_record(session, task_id)
    if record is None:
        raise ValueError(f"Unknown task_id: {task_id}")

    candidate = session.exec(
        select(ClipCandidate).where(ClipCandidate.task_id == task_id).where(ClipCandidate.id == candidate_id)
    ).first()
    if candidate is None:
        raise LookupError(f"Clip candidate {candidate_id} not found for task {task_id}")

    source_video_path = _resolve_source_video_path(task_id, record)
    source_duration_s = _resolve_source_duration_seconds(task_id, record)
    clip_start_s = float(candidate.start_seconds if start_s is None else start_s)
    clip_end_s = float(candidate.end_seconds if end_s is None else end_s)
    _validate_range(clip_start_s, clip_end_s, source_duration_s)

    task_dirs = ensure_task_dirs(task_id)
    output_path = task_dirs["exports"] / _build_export_filename(clip_start_s, clip_end_s)
    log_path = log_file_for_stage(task_id, "export")
    settings = get_settings()
    ffmpeg_args = [
        settings.ffmpeg_binary,
        "-y",
        "-ss",
        _format_ffmpeg_seconds(clip_start_s),
        "-to",
        _format_ffmpeg_seconds(clip_end_s),
        "-i",
        str(source_video_path),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        str(output_path),
    ]
    ffmpeg_result = run_logged_command(ffmpeg_args, log_path=log_path)
    if ffmpeg_result.returncode != 0 or not output_path.exists():
        set_stage_status(session, task_id=task_id, stage_name="export", status="failed", summary="ffmpeg_failed")
        session.commit()
        raise ClipExportFailure(code="ffmpeg_failed", message=ffmpeg_result.stderr or "ffmpeg failed during clip export")

    artifact = _persist_export_artifact(
        session,
        task_id=task_id,
        candidate_id=candidate_id,
        output_path=output_path,
        start_s=clip_start_s,
        end_s=clip_end_s,
        source_duration_s=source_duration_s,
        source_video_path=source_video_path,
    )
    candidate.status = "exported"
    session.add(candidate)
    set_stage_status(
        session,
        task_id=task_id,
        stage_name="export",
        status="success",
        summary=f"Exported clip {output_path.name}",
    )
    return ClipExportResult(
        task_id=task_id,
        candidate_id=candidate_id,
        start_s=clip_start_s,
        end_s=clip_end_s,
        output_path=output_path,
        artifact_id=int(artifact.id),
    )


def _resolve_source_video_path(task_id: str, record) -> Path:
    task_dirs = ensure_task_dirs(task_id)
    raw_dir = task_dirs["raw"]
    preferred = raw_dir / "source.mp4"
    if preferred.exists():
        return preferred

    for artifact in reversed(record.artifacts):
        if artifact.stage_name == "ingest" and artifact.kind == "source_video":
            candidate = Path(artifact.path)
            if candidate.exists():
                return candidate

    raw_files = sorted(path for path in raw_dir.iterdir() if path.is_file()) if raw_dir.exists() else []
    if raw_files:
        return raw_files[0]
    raise ClipExportFailure(code="missing_input", message="Clip export requires a downloaded source video before export can run.")


def _resolve_source_duration_seconds(task_id: str, record) -> float:
    task_dirs = ensure_task_dirs(task_id)
    preferred_probe = task_dirs["work"] / "media-probe.json"
    candidate_paths = [preferred_probe]
    for artifact in reversed(record.artifacts):
        if artifact.stage_name == "media_prep" and artifact.kind == "media_probe":
            candidate_paths.append(Path(artifact.path))

    for candidate_path in candidate_paths:
        if not candidate_path.exists():
            continue
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        duration = _coerce_duration(payload)
        if duration is not None:
            return duration

    for artifact in reversed(record.artifacts):
        if artifact.stage_name == "media_prep" and artifact.kind == "media_probe":
            payload = json.loads(artifact.metadata_json)
            duration = _coerce_duration(payload.get("ffprobe_metadata"))
            if duration is not None:
                return duration

    raise ClipExportFailure(code="missing_input", message="Clip export requires media probe metadata with source duration.")


def _coerce_duration(payload: object) -> float | None:
    if not isinstance(payload, dict):
        return None
    format_payload = payload.get("format")
    if not isinstance(format_payload, dict):
        return None
    duration = format_payload.get("duration")
    try:
        return float(duration)
    except (TypeError, ValueError):
        return None


def _validate_range(start_s: float, end_s: float, source_duration_s: float) -> None:
    if start_s < 0 or end_s <= start_s:
        raise ClipExportFailure(code="invalid_range", message="Clip range must have non-negative bounds and end after start.")
    if end_s > source_duration_s:
        raise ClipExportFailure(
            code="invalid_range",
            message=f"Clip range {start_s:.3f}-{end_s:.3f}s falls outside the source duration {source_duration_s:.3f}s.",
        )


def _build_export_filename(start_s: float, end_s: float) -> str:
    start_ms = int(round(start_s * 1000))
    end_ms = int(round(end_s * 1000))
    return f"clip-{start_ms:08d}-{end_ms:08d}.mp4"


def _format_ffmpeg_seconds(seconds: float) -> str:
    return f"{seconds:.3f}"


def _persist_export_artifact(
    session: Session,
    *,
    task_id: str,
    candidate_id: int,
    output_path: Path,
    start_s: float,
    end_s: float,
    source_duration_s: float,
    source_video_path: Path,
) -> Artifact:
    existing = session.exec(
        select(Artifact)
        .where(Artifact.task_id == task_id)
        .where(Artifact.stage_name == "export")
        .where(Artifact.kind == "clip_export")
        .where(Artifact.path == str(output_path))
    ).first()
    metadata = {
        "candidate_id": candidate_id,
        "start_s": start_s,
        "end_s": end_s,
        "source_duration_s": source_duration_s,
        "source_video_path": str(source_video_path),
        "filename": output_path.name,
    }
    if existing is not None:
        existing.metadata_json = json.dumps(metadata, sort_keys=True)
        session.add(existing)
        session.flush()
        session.refresh(existing)
        return existing
    return persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="export",
        kind="clip_export",
        path=output_path,
        metadata=metadata,
    )
