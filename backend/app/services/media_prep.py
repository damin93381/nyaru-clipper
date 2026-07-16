from __future__ import annotations

import json
import math
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import Artifact, Task
from app.services.media_chunks import (
    MediaChunk,
    MediaChunkFailure,
    MediaChunkManifest,
    build_media_chunk_manifest,
    load_media_chunk_manifest,
    media_chunk_manifest_path,
    write_media_chunk_manifest_atomically,
)
from app.services.pipeline_support import run_logged_command, set_stage_status
from app.services.storage import ensure_task_dirs, get_task_root, log_file_for_stage, persist_artifact_metadata
from app.settings import get_settings


_WAV_SAMPLE_RATE_HZ = 16000
_WAV_CHANNELS = 1
_WAV_SAMPLE_WIDTH_BYTES = 2


@dataclass(slots=True)
class MediaPrepResult:
    source_video_path: Path
    chunk_manifest: MediaChunkManifest
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
    redactions = {str(source_video_path): source_locator} if source_locator is not None else None

    ffprobe_result = run_logged_command(
        [
            settings.ffprobe_binary,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(source_video_path),
        ],
        log_path=log_path,
        redactions=redactions,
    )
    if ffprobe_result.returncode != 0:
        _fail_media_prep(session, task_id=task_id, summary="ffprobe_failed")
        raise MediaPrepFailure(_safe_source_error(ffprobe_result.stderr or "ffprobe failed", source_video_path, source_locator))

    try:
        ffprobe_metadata = json.loads(ffprobe_result.stdout)
    except json.JSONDecodeError as exc:
        _fail_media_prep(session, task_id=task_id, summary="ffprobe_failed")
        raise MediaPrepFailure("ffprobe did not return valid JSON") from exc
    if not isinstance(ffprobe_metadata, dict):
        _fail_media_prep(session, task_id=task_id, summary="ffprobe_failed")
        raise MediaPrepFailure("ffprobe did not return an object")

    try:
        source_duration_seconds = _source_duration_seconds(ffprobe_metadata)
    except ValueError as exc:
        _fail_media_prep(session, task_id=task_id, summary="ffprobe_failed")
        raise MediaPrepFailure("ffprobe duration is invalid") from exc

    persisted_ffprobe_metadata = _safe_source_metadata(ffprobe_metadata, source_video_path, source_locator)
    metadata_path = work_dir / "media-probe.json"
    metadata_path.write_text(json.dumps(persisted_ffprobe_metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    manifest_path = media_chunk_manifest_path(work_dir)
    try:
        chunk_manifest = load_media_chunk_manifest(
            manifest_path,
            source_duration_seconds=source_duration_seconds,
        )
    except MediaChunkFailure:
        chunk_manifest = build_media_chunk_manifest(source_duration_seconds, work_dir=work_dir)
        _invalidate_existing_chunk_audio(work_dir)

    for chunk in chunk_manifest.chunks:
        if _has_valid_chunk_audio(chunk):
            continue
        try:
            _create_chunk_audio(
                chunk,
                source_video_path=source_video_path,
                ffmpeg_binary=settings.ffmpeg_binary,
                log_path=log_path,
                redactions=redactions,
                source_locator=source_locator,
            )
        except MediaPrepFailure:
            _fail_media_prep(session, task_id=task_id, summary="ffmpeg_failed")
            raise

    try:
        write_media_chunk_manifest_atomically(manifest_path, chunk_manifest)
    except MediaChunkFailure as exc:
        _fail_media_prep(session, task_id=task_id, summary="ffmpeg_failed")
        raise MediaPrepFailure("media chunk manifest could not be written") from exc

    _persist_media_prep_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="media_prep",
        kind="media_probe",
        path=metadata_path,
        metadata={"ffprobe_metadata": persisted_ffprobe_metadata},
    )
    _persist_media_prep_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="media_prep",
        kind="media_chunk_manifest",
        path=manifest_path,
        metadata={
            "source_duration_seconds": source_duration_seconds,
            "chunk_seconds": chunk_manifest.chunk_seconds,
            "chunk_count": len(chunk_manifest.chunks),
        },
    )
    for chunk in chunk_manifest.chunks:
        _persist_media_prep_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="media_prep",
            kind="asr_audio_chunk",
            path=chunk.audio_path,
            metadata={
                "chunk_id": chunk.id,
                "index": chunk.index,
                "start_seconds": chunk.start_seconds,
                "end_seconds": chunk.end_seconds,
                "audio_format": "wav",
                "channels": _WAV_CHANNELS,
                "sample_rate_hz": _WAV_SAMPLE_RATE_HZ,
                "source_video_path": source_locator or str(source_video_path),
            },
        )
    set_stage_status(session, task_id=task_id, stage_name="media_prep", status="success", summary="Prepared ASR WAV chunks")
    return MediaPrepResult(
        source_video_path=source_video_path,
        chunk_manifest=chunk_manifest,
        ffprobe_metadata=ffprobe_metadata,
    )


def _source_duration_seconds(metadata: dict[str, Any]) -> float:
    format_metadata = metadata.get("format")
    if not isinstance(format_metadata, dict):
        raise ValueError("format is missing")
    duration = format_metadata.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, str | int | float):
        raise ValueError("duration is missing")
    parsed_duration = float(duration)
    if not math.isfinite(parsed_duration) or parsed_duration < 0:
        raise ValueError("duration must be finite and non-negative")
    return parsed_duration


def _has_valid_chunk_audio(chunk: MediaChunk) -> bool:
    if not chunk.audio_path.is_file():
        return False
    try:
        with wave.open(str(chunk.audio_path), "rb") as input_audio:
            matches_format = (
                input_audio.getnchannels() == _WAV_CHANNELS
                and input_audio.getsampwidth() == _WAV_SAMPLE_WIDTH_BYTES
                and input_audio.getframerate() == _WAV_SAMPLE_RATE_HZ
            )
            actual_duration_seconds = input_audio.getnframes() / input_audio.getframerate()
    except (OSError, wave.Error):
        return False
    expected_duration_seconds = chunk.end_seconds - chunk.start_seconds
    return matches_format and abs(actual_duration_seconds - expected_duration_seconds) <= 1 / _WAV_SAMPLE_RATE_HZ


def _invalidate_existing_chunk_audio(work_dir: Path) -> None:
    for audio_path in (work_dir / "asr-audio-chunks").glob("*.wav"):
        audio_path.unlink()


def _persist_media_prep_artifact_metadata(
    session: Session,
    *,
    task_id: str,
    stage_name: str,
    kind: str,
    path: Path,
    metadata: dict[str, Any],
) -> None:
    artifact = session.exec(
        select(Artifact)
        .where(Artifact.task_id == task_id)
        .where(Artifact.stage_name == stage_name)
        .where(Artifact.kind == kind)
        .where(Artifact.path == str(path))
    ).first()
    if artifact is not None:
        artifact.metadata_json = json.dumps(metadata, sort_keys=True)
        session.add(artifact)
        task = session.get(Task, task_id)
        if task is not None:
            task.storage_bytes = sum(
                candidate.stat().st_size
                for candidate in get_task_root(task_id).rglob("*")
                if candidate.is_file()
            )
            session.add(task)
        return
    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name=stage_name,
        kind=kind,
        path=path,
        metadata=metadata,
    )


def _create_chunk_audio(
    chunk: MediaChunk,
    *,
    source_video_path: Path,
    ffmpeg_binary: str,
    log_path: Path,
    redactions: dict[str, str] | None,
    source_locator: str | None,
) -> None:
    chunk.audio_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_filename = tempfile.mkstemp(
        dir=chunk.audio_path.parent,
        prefix=f".{chunk.id}.",
        suffix=".wav",
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_filename)
    try:
        ffmpeg_result = run_logged_command(
            [
                ffmpeg_binary,
                "-y",
                "-i",
                str(source_video_path),
                "-ss",
                str(chunk.start_seconds),
                "-t",
                str(chunk.end_seconds - chunk.start_seconds),
                "-vn",
                "-ac",
                str(_WAV_CHANNELS),
                "-ar",
                str(_WAV_SAMPLE_RATE_HZ),
                "-c:a",
                "pcm_s16le",
                "-avoid_negative_ts",
                "make_zero",
                str(temporary_path),
            ],
            log_path=log_path,
            redactions=redactions,
        )
        if ffmpeg_result.returncode != 0 or not _has_valid_chunk_audio(
            MediaChunk(chunk.index, chunk.start_seconds, chunk.end_seconds, temporary_path)
        ):
            raise MediaPrepFailure(_safe_source_error(ffmpeg_result.stderr or "ffmpeg failed", source_video_path, source_locator))
        temporary_path.replace(chunk.audio_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _fail_media_prep(session: Session, *, task_id: str, summary: str) -> None:
    set_stage_status(session, task_id=task_id, stage_name="media_prep", status="failed", summary=summary)
    session.commit()


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
