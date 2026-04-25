from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.repositories.tasks import get_task_record
from app.services.pipeline_support import append_stage_log, set_stage_status
from app.services.storage import ensure_task_dirs, log_file_for_stage, persist_artifact_metadata
from app.services.subtitles import SubtitleSegment, SubtitleWord, write_subtitle_outputs
from app.settings import Settings, get_settings


@dataclass(slots=True)
class AsrStageResult:
    audio_path: Path
    transcript_path: Path
    subtitle_path: Path
    raw_alignment_path: Path
    model_metadata: dict[str, Any]
    elapsed_seconds: float
    segments: list[SubtitleSegment]


class AsrFailure(RuntimeError):
    def __init__(self, *, code: str, message: str):
        super().__init__(message)
        self.code = code


def _load_whisperx_module():
    return importlib.import_module("whisperx")


def transcribe_task_audio(session: Session, task_id: str) -> AsrStageResult:
    record = get_task_record(session, task_id)
    if record is None:
        raise ValueError(f"Unknown task_id: {task_id}")

    settings = get_settings()
    audio_path = _resolve_input_audio_path(task_id, record)
    task_dirs = ensure_task_dirs(task_id)
    work_dir = task_dirs["work"]
    log_path = log_file_for_stage(task_id, "asr")

    append_stage_log(log_path, f"asr_input={audio_path}")
    model_metadata = _build_model_metadata(settings)
    raw_alignment_path = work_dir / "asr-alignment-raw.json"

    started_at = time.perf_counter()
    try:
        whisperx = _load_whisperx_module()
        model = whisperx.load_model(
            settings.whisperx_model_name,
            settings.whisperx_device,
            compute_type=settings.whisperx_compute_type,
            download_root=str(settings.whisperx_model_cache_dir) if settings.whisperx_model_cache_dir else None,
        )
        transcription_result = model.transcribe(
            str(audio_path),
            batch_size=settings.whisperx_batch_size,
            language=settings.whisperx_language,
        )
        language_code = transcription_result.get("language") or settings.whisperx_language
        align_model, align_metadata = whisperx.load_align_model(
            language_code=language_code,
            device=settings.whisperx_device,
            model_name=settings.whisperx_alignment_model_name,
        )
        aligned_result = whisperx.align(
            transcription_result.get("segments") or [],
            align_model,
            align_metadata,
            str(audio_path),
            settings.whisperx_device,
            return_char_alignments=False,
        )
        raw_alignment_path.write_text(
            json.dumps(aligned_result, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="asr",
            kind="alignment_raw",
            path=raw_alignment_path,
            metadata={
                "elapsed_seconds": elapsed_seconds,
                "model_metadata": model_metadata,
                "source_audio_path": str(audio_path),
            },
        )
        segments = _normalize_aligned_segments(aligned_result.get("segments"))
        transcript_path, subtitle_path = write_subtitle_outputs(
            work_dir,
            segments,
            model_metadata=model_metadata,
            elapsed_seconds=elapsed_seconds,
        )
    except Exception as exc:
        failure = _classify_asr_exception(exc, settings=settings)
        append_stage_log(log_path, f"classified_failure={failure.code}")
        append_stage_log(log_path, str(failure))
        set_stage_status(session, task_id=task_id, stage_name="asr", status="failed", summary=failure.code)
        session.commit()
        raise failure from exc

    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="asr",
        kind="transcript_json",
        path=transcript_path,
        metadata={
            "elapsed_seconds": elapsed_seconds,
            "model_metadata": model_metadata,
            "segment_count": len(segments),
            "source_audio_path": str(audio_path),
        },
    )
    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="asr",
        kind="subtitle_srt",
        path=subtitle_path,
        metadata={
            "elapsed_seconds": elapsed_seconds,
            "model_metadata": model_metadata,
            "segment_count": len(segments),
            "language": settings.whisperx_language,
        },
    )
    set_stage_status(
        session,
        task_id=task_id,
        stage_name="asr",
        status="success",
        summary="Generated aligned transcript and Chinese subtitles",
    )
    return AsrStageResult(
        audio_path=audio_path,
        transcript_path=transcript_path,
        subtitle_path=subtitle_path,
        raw_alignment_path=raw_alignment_path,
        model_metadata=model_metadata,
        elapsed_seconds=elapsed_seconds,
        segments=segments,
    )


def _build_model_metadata(settings: Settings) -> dict[str, Any]:
    if not settings.whisperx_model_name:
        raise AsrFailure(
            code="missing_model",
            message="WhisperX model configuration is missing. Set APP_WHISPERX_MODEL_NAME and provision the model before retrying.",
        )
    return {
        "provider": "whisperx",
        "model_name": settings.whisperx_model_name,
        "alignment_model_name": settings.whisperx_alignment_model_name,
        "device": settings.whisperx_device,
        "compute_type": settings.whisperx_compute_type,
        "language": settings.whisperx_language,
        "batch_size": settings.whisperx_batch_size,
    }


def _resolve_input_audio_path(task_id: str, record) -> Path:
    task_dirs = ensure_task_dirs(task_id)
    preferred = task_dirs["work"] / "asr-input.wav"
    if preferred.exists():
        return preferred

    for artifact in reversed(record.artifacts):
        if artifact.stage_name == "media_prep" and artifact.kind == "asr_audio":
            candidate = Path(artifact.path)
            if candidate.exists():
                return candidate
    raise AsrFailure(
        code="missing_input",
        message="ASR input WAV is missing. Re-run media preparation or restore the normalized audio artifact before retrying.",
    )


def _normalize_aligned_segments(raw_segments: Any) -> list[SubtitleSegment]:
    if not isinstance(raw_segments, list) or not raw_segments:
        raise AsrFailure(code="alignment_failed", message="WhisperX alignment did not return any timed segments.")

    normalized: list[SubtitleSegment] = []
    for index, raw_segment in enumerate(raw_segments, start=1):
        if not isinstance(raw_segment, dict):
            raise AsrFailure(code="alignment_failed", message="WhisperX alignment returned an invalid segment payload.")
        start_seconds = _coerce_float(raw_segment.get("start"))
        end_seconds = _coerce_float(raw_segment.get("end"))
        text = str(raw_segment.get("text") or "").strip()
        if start_seconds is None or end_seconds is None or end_seconds < start_seconds or not text:
            raise AsrFailure(code="alignment_failed", message="WhisperX alignment returned a segment without usable timestamps.")

        words: list[SubtitleWord] = []
        raw_words = raw_segment.get("words")
        if isinstance(raw_words, list):
            for raw_word in raw_words:
                if not isinstance(raw_word, dict):
                    continue
                word_text = str(raw_word.get("word") or raw_word.get("text") or "").strip()
                word_start = _coerce_float(raw_word.get("start"))
                word_end = _coerce_float(raw_word.get("end"))
                if not word_text or word_start is None or word_end is None:
                    continue
                words.append(
                    SubtitleWord(
                        text=word_text,
                        start_seconds=word_start,
                        end_seconds=word_end,
                        confidence=_coerce_float(raw_word.get("score") or raw_word.get("confidence")),
                    )
                )

        normalized.append(
            SubtitleSegment(
                id=str(raw_segment.get("id") or f"seg-{index:04d}"),
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                text=text,
                words=words or None,
            )
        )
    return normalized


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _classify_asr_exception(exc: Exception, *, settings: Settings) -> AsrFailure:
    if isinstance(exc, AsrFailure):
        return exc

    message = str(exc).strip() or exc.__class__.__name__
    normalized = message.lower()
    if isinstance(exc, ModuleNotFoundError):
        return AsrFailure(
            code="missing_model",
            message="WhisperX is not installed or available. Install the provider and provision the configured model before retrying.",
        )
    if isinstance(exc, FileNotFoundError) or "model" in normalized and any(marker in normalized for marker in ["missing", "not found", "unavailable"]):
        return AsrFailure(
            code="missing_model",
            message=(
                f"WhisperX model '{settings.whisperx_model_name}' is unavailable. "
                "Provision the configured model files/cache before retrying."
            ),
        )
    if any(marker in normalized for marker in ["out of memory", "cuda oom", "cuda out of memory"]):
        return AsrFailure(
            code="oom",
            message="WhisperX ran out of memory. Free GPU/CPU memory or lower the configured model footprint before retrying.",
        )
    return AsrFailure(
        code="alignment_failed",
        message=f"WhisperX alignment failed: {message}",
    )
