from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.services.pipeline_support import run_logged_command, set_stage_status
from app.services.storage import ensure_task_dirs, log_file_for_stage, persist_artifact_metadata
from app.settings import get_settings


@dataclass(slots=True)
class MediaPrepResult:
    source_video_path: Path
    audio_path: Path
    ffprobe_metadata: dict[str, Any]


class MediaPrepFailure(RuntimeError):
    pass


def prepare_media_for_asr(
    session: Session,
    task_id: str,
    source_video_path: Path,
    *,
    source_locator: str | None = None,
) -> MediaPrepResult:
    task_dirs = ensure_task_dirs(task_id)
    work_dir = task_dirs["work"]
    log_path = log_file_for_stage(task_id, "media_prep")
    settings = get_settings()

    ffprobe_args = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source_video_path),
    ]
    redactions = {str(source_video_path): source_locator} if source_locator is not None else None
    ffprobe_result = run_logged_command(ffprobe_args, log_path=log_path, redactions=redactions)
    if ffprobe_result.returncode != 0:
        set_stage_status(session, task_id=task_id, stage_name="media_prep", status="failed", summary="ffprobe_failed")
        session.commit()
        raise MediaPrepFailure(_safe_source_error(ffprobe_result.stderr or "ffprobe failed", source_video_path, source_locator))

    try:
        ffprobe_metadata = json.loads(ffprobe_result.stdout)
    except json.JSONDecodeError as exc:
        set_stage_status(session, task_id=task_id, stage_name="media_prep", status="failed", summary="ffprobe_failed")
        session.commit()
        raise MediaPrepFailure("ffprobe did not return valid JSON") from exc

    persisted_ffprobe_metadata = _safe_source_metadata(ffprobe_metadata, source_video_path, source_locator)
    metadata_path = work_dir / "media-probe.json"
    metadata_path.write_text(json.dumps(persisted_ffprobe_metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    audio_path = work_dir / "asr-input.wav"
    ffmpeg_args = [
        settings.ffmpeg_binary,
        "-y",
        "-i",
        str(source_video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]
    ffmpeg_result = run_logged_command(ffmpeg_args, log_path=log_path, redactions=redactions)
    if ffmpeg_result.returncode != 0 or not audio_path.exists():
        set_stage_status(session, task_id=task_id, stage_name="media_prep", status="failed", summary="ffmpeg_failed")
        session.commit()
        raise MediaPrepFailure(_safe_source_error(ffmpeg_result.stderr or "ffmpeg failed", source_video_path, source_locator))

    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="media_prep",
        kind="media_probe",
        path=metadata_path,
        metadata={"ffprobe_metadata": persisted_ffprobe_metadata},
    )
    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="media_prep",
        kind="asr_audio",
        path=audio_path,
        metadata={
            "audio_format": "wav",
            "channels": 1,
            "sample_rate_hz": 16000,
            "source_video_path": source_locator or str(source_video_path),
        },
    )
    set_stage_status(session, task_id=task_id, stage_name="media_prep", status="success", summary="Prepared ffprobe metadata and ASR wav")
    return MediaPrepResult(
        source_video_path=source_video_path,
        audio_path=audio_path,
        ffprobe_metadata=ffprobe_metadata,
    )


def _safe_source_metadata(metadata: dict[str, Any], source_video_path: Path, source_locator: str | None) -> dict[str, Any]:
    """Replace the trusted runtime path in probe metadata before it reaches durable storage."""
    if source_locator is None:
        return metadata
    serialized = json.dumps(metadata, ensure_ascii=False)
    sanitized = json.loads(serialized.replace(str(source_video_path), source_locator))
    return sanitized if isinstance(sanitized, dict) else metadata


def _safe_source_error(message: str, source_video_path: Path, source_locator: str | None) -> str:
    """Keep command failures useful without retaining a trusted local path."""
    if source_locator is None:
        return message
    return message.replace(str(source_video_path), source_locator)
