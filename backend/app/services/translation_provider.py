from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlmodel import Session

from app.repositories.tasks import get_task_record
from app.services.pipeline_support import append_stage_log, set_stage_status
from app.services.storage import ensure_task_dirs, log_file_for_stage, persist_artifact_metadata
from app.services.subtitles import SubtitleSegment, SubtitleWord, write_bilingual_subtitle_outputs
from app.services.translation_hf import HuggingFaceTranslationProvider
from app.settings import Settings, get_settings


class TranslationProvider(Protocol):
    @property
    def metadata(self) -> dict[str, object]: ...

    def translate_segments(self, segments: list[SubtitleSegment]) -> list[str]: ...


@dataclass(slots=True)
class TranslationStageResult:
    source_transcript_path: Path
    transcript_path: Path
    subtitle_path: Path
    model_metadata: dict[str, object]
    elapsed_seconds: float
    segments: list[SubtitleSegment]
    translated_texts: list[str]


class TranslationFailure(RuntimeError):
    def __init__(self, *, code: str, message: str):
        super().__init__(message)
        self.code = code


def build_translation_provider(settings: Settings | None = None) -> TranslationProvider:
    runtime = settings or get_settings()
    if runtime.translation_provider != "hf":
        raise TranslationFailure(
            code="unsupported_provider",
            message=f"Unsupported translation provider '{runtime.translation_provider}'.",
        )
    if not runtime.translation_model_name:
        raise TranslationFailure(
            code="missing_model",
            message="Translation model configuration is missing. Set APP_TRANSLATION_MODEL_NAME before retrying.",
        )
    return HuggingFaceTranslationProvider(
        model_name=runtime.translation_model_name,
        device=runtime.translation_device,
        source_language_code=runtime.translation_source_language_code,
        target_language_code=runtime.translation_target_language_code,
        max_new_tokens=runtime.translation_max_new_tokens,
    )


def translate_task_subtitles(session: Session, task_id: str) -> TranslationStageResult:
    record = get_task_record(session, task_id)
    if record is None:
        raise ValueError(f"Unknown task_id: {task_id}")

    settings = get_settings()
    source_transcript_path = _resolve_source_transcript_path(task_id, record)
    segments = _load_segments_from_transcript(source_transcript_path)
    task_dirs = ensure_task_dirs(task_id)
    log_path = log_file_for_stage(task_id, "translation")
    provider = build_translation_provider(settings)

    append_stage_log(log_path, f"translation_input={source_transcript_path}")
    append_stage_log(log_path, f"translation_model={provider.metadata.get('model_name')}")

    started_at = time.perf_counter()
    try:
        translated_texts = provider.translate_segments(segments)
        if len(translated_texts) != len(segments):
            raise TranslationFailure(
                code="translation_failed",
                message=(
                    f"Translation provider '{provider.metadata.get('model_name')}' returned "
                    f"{len(translated_texts)} segments for {len(segments)} source segments."
                ),
            )
        for segment, translated_text in zip(segments, translated_texts, strict=True):
            if not str(translated_text).strip():
                raise TranslationFailure(
                    code="translation_failed",
                    message=(
                        f"Translation provider '{provider.metadata.get('model_name')}' returned an empty result "
                        f"for segment {segment.id}."
                    ),
                )
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        transcript_path, subtitle_path = write_bilingual_subtitle_outputs(
            task_dirs["work"],
            segments,
            translated_texts,
            model_metadata=dict(provider.metadata),
            elapsed_seconds=elapsed_seconds,
        )
    except Exception as exc:
        failure = _classify_translation_exception(exc, provider_metadata=dict(provider.metadata), settings=settings)
        append_stage_log(log_path, f"classified_failure={failure.code}")
        append_stage_log(log_path, str(failure))
        set_stage_status(
            session,
            task_id=task_id,
            stage_name="translation",
            status="failed",
            summary=failure.code,
        )
        session.commit()
        raise failure from exc

    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="translation",
        kind="bilingual_transcript_json",
        path=transcript_path,
        metadata={
            "elapsed_seconds": elapsed_seconds,
            "model_metadata": dict(provider.metadata),
            "segment_count": len(segments),
            "source_transcript_path": str(source_transcript_path),
        },
    )
    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="translation",
        kind="bilingual_subtitle_srt",
        path=subtitle_path,
        metadata={
            "elapsed_seconds": elapsed_seconds,
            "model_metadata": dict(provider.metadata),
            "segment_count": len(segments),
            "source_transcript_path": str(source_transcript_path),
        },
    )
    set_stage_status(
        session,
        task_id=task_id,
        stage_name="translation",
        status="success",
        summary="Generated bilingual Chinese/Japanese subtitles",
    )
    return TranslationStageResult(
        source_transcript_path=source_transcript_path,
        transcript_path=transcript_path,
        subtitle_path=subtitle_path,
        model_metadata=dict(provider.metadata),
        elapsed_seconds=elapsed_seconds,
        segments=segments,
        translated_texts=list(translated_texts),
    )


def _resolve_source_transcript_path(task_id: str, record) -> Path:
    task_dirs = ensure_task_dirs(task_id)
    preferred = task_dirs["work"] / "asr-segments.json"
    if preferred.exists():
        return preferred

    for artifact in reversed(record.artifacts):
        if artifact.stage_name == "asr" and artifact.kind == "transcript_json":
            candidate = Path(artifact.path)
            if candidate.exists():
                return candidate
    raise TranslationFailure(
        code="missing_input",
        message="ASR transcript JSON is missing. Re-run ASR or restore the normalized transcript artifact before retrying.",
    )


def _load_segments_from_transcript(transcript_path: Path) -> list[SubtitleSegment]:
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise TranslationFailure(
            code="missing_input",
            message="ASR transcript JSON does not contain any subtitle segments to translate.",
        )

    segments: list[SubtitleSegment] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict):
            raise TranslationFailure(
                code="missing_input",
                message="ASR transcript JSON contains an invalid segment payload.",
            )
        words = raw_segment.get("words")
        normalized_words = None
        if isinstance(words, list):
            normalized_words = [
                SubtitleWord(
                    text=str(word.get("text") or ""),
                    start_seconds=float(word["start_seconds"]),
                    end_seconds=float(word["end_seconds"]),
                    confidence=float(word["confidence"]) if word.get("confidence") is not None else None,
                )
                for word in words
            ]
        segments.append(
            SubtitleSegment(
                id=str(raw_segment["id"]),
                start_seconds=float(raw_segment["start_seconds"]),
                end_seconds=float(raw_segment["end_seconds"]),
                text=str(raw_segment["text"]),
                words=normalized_words,
            )
        )
    return segments


def _classify_translation_exception(
    exc: Exception,
    *,
    provider_metadata: dict[str, object],
    settings: Settings,
) -> TranslationFailure:
    if isinstance(exc, TranslationFailure):
        return exc

    model_name = str(provider_metadata.get("model_name") or settings.translation_model_name)
    message = str(exc).strip() or exc.__class__.__name__
    normalized = message.lower()
    if isinstance(exc, ModuleNotFoundError):
        return TranslationFailure(
            code="missing_provider",
            message=(
                f"Translation provider dependencies are unavailable for model '{model_name}'. "
                "Install the local Hugging Face runtime before retrying."
            ),
        )
    if isinstance(exc, FileNotFoundError) or "not found" in normalized or "missing" in normalized and "model" in normalized:
        return TranslationFailure(
            code="missing_model",
            message=f"Translation model '{model_name}' is unavailable. Provision the configured model before retrying.",
        )
    return TranslationFailure(
        code="translation_failed",
        message=f"Translation stage failed for model '{model_name}': {message}",
    )
