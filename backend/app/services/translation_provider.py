from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from sqlmodel import Session, select

from app.models import Artifact
from app.repositories.tasks import get_task_record, upsert_task_execution_progress
from app.services.asr_whisperx import AsrFailure, load_verified_merged_asr_artifacts
from app.services.media_chunks import MediaChunk, MediaChunkFailure, load_media_chunk_manifest, media_chunk_manifest_path
from app.services.pipeline_support import append_stage_log, set_stage_status
from app.services.proofread_deepseek import (
    DeepSeekProofreader,
    ProofreadBatchAudit,
    ProofreadFailure,
    ProofreadResult,
    ProofreadSegment,
)
from app.services.storage import ensure_task_dirs, log_file_for_stage, persist_artifact_metadata
from app.services.subtitles import (
    SubtitleSegment,
    write_bilingual_subtitle_outputs,
    write_bilingual_subtitle_outputs_atomically,
)
from app.services.translation_hf import HuggingFaceTranslationProvider
from app.settings import Settings, get_settings


class TranslationProvider(Protocol):
    @property
    def metadata(self) -> dict[str, object]: ...

    def translate_segments(self, segments: list[SubtitleSegment]) -> list[str]: ...


class Proofreader(Protocol):
    def proofread_segments(self, segments: list[ProofreadSegment]) -> ProofreadResult: ...


TRANSLATION_CHUNK_SCHEMA_VERSION: Final = 1
TRANSLATION_CHUNK_DIRECTORY: Final = "translation-chunks"
FINAL_PUBLICATION_ARTIFACT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "bilingual_proofread_audit_json",
        "bilingual_subtitle_srt",
        "bilingual_transcript_json",
    }
)
FINAL_PUBLICATION_FILENAMES: Final[tuple[str, str, str]] = (
    "proofread-audit.json",
    "subtitles.zh-ja.json",
    "subtitles.zh-ja.srt",
)


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


def build_proofreader(settings: Settings) -> Proofreader:
    """Build the server-side-only constrained proofreading boundary."""
    if settings.proofread_provider != "deepseek":
        raise TranslationFailure(
            code="translation_proofread_unsupported_provider",
            message="The configured proofreading provider is unsupported.",
        )
    return DeepSeekProofreader(settings)


def translate_task_subtitles(session: Session, task_id: str) -> TranslationStageResult:
    record = get_task_record(session, task_id)
    if record is None:
        raise ValueError(f"Unknown task_id: {task_id}")

    settings = get_settings()
    task_dirs = ensure_task_dirs(task_id)
    log_path = log_file_for_stage(task_id, "translation")
    provider = build_translation_provider(settings)
    proofreader = build_proofreader(settings)

    try:
        media_chunks = load_media_chunk_manifest(media_chunk_manifest_path(task_dirs["work"])).chunks
    except MediaChunkFailure as exc:
        raise TranslationFailure(
            code="missing_input",
            message="Translation media chunk manifest is missing or invalid. Re-run media preparation before retrying.",
        ) from exc
    try:
        verified_asr = load_verified_merged_asr_artifacts(task_id, work_dir=task_dirs["work"], chunks=media_chunks)
    except AsrFailure as exc:
        raise TranslationFailure(code=exc.code, message=str(exc)) from exc
    source_transcript_path = verified_asr.transcript_path
    segments = verified_asr.segments
    chunk_segments = _partition_segments_by_media_chunk(segments, media_chunks)

    append_stage_log(log_path, f"translation_input={source_transcript_path}")
    append_stage_log(log_path, f"translation_model={provider.metadata.get('model_name')}")

    started_at = time.perf_counter()
    try:
        translated_texts = _translate_media_chunks(
            session,
            task_id=task_id,
            work_dir=task_dirs["work"],
            provider=provider,
            chunk_segments=chunk_segments,
        )
        _record_translation_merge_progress(session, task_id=task_id, total_count=len(chunk_segments))
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        preproofread_transcript_path, preproofread_subtitle_path = write_bilingual_subtitle_outputs(
            task_dirs["work"],
            segments,
            translated_texts,
            model_metadata=dict(provider.metadata),
            elapsed_seconds=elapsed_seconds,
            transcript_filename="subtitles.zh-ja.preproofread.json",
            srt_filename="subtitles.zh-ja.preproofread.srt",
        )
        _persist_preproofread_artifacts(
            session,
            task_id=task_id,
            source_transcript_path=source_transcript_path,
            transcript_path=preproofread_transcript_path,
            subtitle_path=preproofread_subtitle_path,
            provider_metadata=dict(provider.metadata),
            elapsed_seconds=elapsed_seconds,
            segment_count=len(segments),
        )
        _record_translation_proofread_progress(session, task_id=task_id, total_count=len(segments))
        proofread_result = proofreader.proofread_segments(_to_proofread_segments(segments, translated_texts))
        final_segments, final_translated_texts = _validated_final_proofread_output(
            source_segments=segments,
            proofread_result=proofread_result,
        )
        audit_path = _write_proofread_audit_atomically(
            task_dirs["work"],
            audits=proofread_result.batch_audits,
            proofread_model=settings.deepseek_model,
        )
        final_metadata = {
            "translation": dict(provider.metadata),
            "proofreader": {"provider": settings.proofread_provider, "model": settings.deepseek_model},
        }
        transcript_path, subtitle_path = write_bilingual_subtitle_outputs_atomically(
            task_dirs["work"],
            final_segments,
            final_translated_texts,
            model_metadata=final_metadata,
            elapsed_seconds=elapsed_seconds,
        )
        _persist_final_translation_publication(
            session,
            task_id=task_id,
            audit_path=audit_path,
            transcript_path=transcript_path,
            subtitle_path=subtitle_path,
            proofread_model=settings.deepseek_model,
            proofread_batch_count=len(proofread_result.batch_audits),
            elapsed_seconds=elapsed_seconds,
            segment_count=len(final_segments),
        )
    except Exception as exc:
        _discard_failed_final_publication(session, task_id=task_id, work_dir=task_dirs["work"])
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

    return TranslationStageResult(
        source_transcript_path=source_transcript_path,
        transcript_path=transcript_path,
        subtitle_path=subtitle_path,
        model_metadata=dict(provider.metadata),
        elapsed_seconds=elapsed_seconds,
        segments=final_segments,
        translated_texts=final_translated_texts,
    )


def _persist_final_translation_publication(
    session: Session,
    *,
    task_id: str,
    audit_path: Path,
    transcript_path: Path,
    subtitle_path: Path,
    proofread_model: str,
    proofread_batch_count: int,
    elapsed_seconds: float,
    segment_count: int,
) -> None:
    """Persist the canonical publication as one savepoint-scoped database change."""
    with session.begin_nested():
        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="translation",
            kind="bilingual_proofread_audit_json",
            path=audit_path,
            metadata={"model": proofread_model, "batch_count": proofread_batch_count},
        )
        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="translation",
            kind="bilingual_transcript_json",
            path=transcript_path,
            metadata={"elapsed_seconds": elapsed_seconds, "segment_count": segment_count},
        )
        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="translation",
            kind="bilingual_subtitle_srt",
            path=subtitle_path,
            metadata={"elapsed_seconds": elapsed_seconds, "segment_count": segment_count},
        )
        set_stage_status(
            session,
            task_id=task_id,
            stage_name="translation",
            status="success",
            summary="Generated proofread bilingual Chinese/Japanese subtitles",
        )
        session.flush()


def _discard_failed_final_publication(session: Session, *, task_id: str, work_dir: Path) -> None:
    """Remove only canonical proofread publication state while preserving the diagnostic baseline."""
    artifacts = session.exec(
        select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "translation")
    ).all()
    for artifact in artifacts:
        if artifact.kind in FINAL_PUBLICATION_ARTIFACT_KINDS:
            session.delete(artifact)
    for filename in FINAL_PUBLICATION_FILENAMES:
        (work_dir / filename).unlink(missing_ok=True)


def _persist_preproofread_artifacts(
    session: Session,
    *,
    task_id: str,
    source_transcript_path: Path,
    transcript_path: Path,
    subtitle_path: Path,
    provider_metadata: dict[str, object],
    elapsed_seconds: float,
    segment_count: int,
) -> None:
    """Persist the diagnostic baseline before an external proofread attempt may fail."""
    metadata = {
        "elapsed_seconds": elapsed_seconds,
        "model_metadata": provider_metadata,
        "segment_count": segment_count,
        "source_transcript_path": str(source_transcript_path),
    }
    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="translation",
        kind="bilingual_preproofread_transcript_json",
        path=transcript_path,
        metadata=metadata,
    )
    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="translation",
        kind="bilingual_preproofread_subtitle_srt",
        path=subtitle_path,
        metadata=metadata,
    )


def _to_proofread_segments(
    segments: list[SubtitleSegment], translated_texts: list[str]
) -> list[ProofreadSegment]:
    return [
        ProofreadSegment(
            id=segment.id,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            text=segment.text,
            translated_text=translated_text,
        )
        for segment, translated_text in zip(segments, translated_texts, strict=True)
    ]


def _validated_final_proofread_output(
    *, source_segments: list[SubtitleSegment], proofread_result: ProofreadResult
) -> tuple[list[SubtitleSegment], list[str]]:
    """Rebind constrained proofread text to the source rows that own timing and word data."""
    if len(proofread_result.segments) != len(source_segments):
        raise TranslationFailure(
            code="translation_proofread_invalid_response",
            message="DeepSeek proofreading did not return every requested subtitle row.",
        )
    final_segments: list[SubtitleSegment] = []
    translated_texts: list[str] = []
    for source, corrected in zip(source_segments, proofread_result.segments, strict=True):
        if (
            corrected.id != source.id
            or corrected.start_seconds != source.start_seconds
            or corrected.end_seconds != source.end_seconds
            or not corrected.text.strip()
            or not corrected.translated_text.strip()
        ):
            raise TranslationFailure(
                code="translation_proofread_invalid_response",
                message="DeepSeek proofreading violated the subtitle identity or timing contract.",
            )
        final_segments.append(
            SubtitleSegment(
                id=source.id,
                start_seconds=source.start_seconds,
                end_seconds=source.end_seconds,
                text=corrected.text.strip(),
                words=source.words,
            )
        )
        translated_texts.append(corrected.translated_text.strip())
    return final_segments, translated_texts


def _write_proofread_audit_atomically(
    work_dir: Path, *, audits: list[ProofreadBatchAudit], proofread_model: str
) -> Path:
    """Persist only aggregate audit metadata, never prompts, credentials, or provider bodies."""
    audit_path = work_dir / "proofread-audit.json"
    payload = {
        "provider": "deepseek",
        "model": proofread_model,
        "batch_count": len(audits),
        "batches": [
            {
                "batch_index": audit.batch_index,
                "model": audit.model,
                "attempt_count": audit.attempt_count,
                "elapsed_seconds": audit.elapsed_seconds,
                "changed_segment_count": audit.changed_segment_count,
                "token_usage": dict(audit.token_usage),
            }
            for audit in audits
        ],
    }
    descriptor, temporary_name = tempfile.mkstemp(dir=work_dir, prefix=f".{audit_path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        Path(temporary_name).replace(audit_path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return audit_path


def _partition_segments_by_media_chunk(
    segments: list[SubtitleSegment], chunks: tuple[MediaChunk, ...]
) -> list[tuple[MediaChunk, list[SubtitleSegment]]]:
    """Assign each source-global caption to exactly one validated media chunk."""
    if not chunks:
        raise TranslationFailure(code="missing_input", message="Translation media chunk manifest contains no audio chunks.")

    partitioned: list[tuple[MediaChunk, list[SubtitleSegment]]] = []
    segment_offset = 0
    for chunk in chunks:
        current: list[SubtitleSegment] = []
        while segment_offset < len(segments):
            segment = segments[segment_offset]
            if segment.start_seconds >= chunk.end_seconds:
                break
            if segment.start_seconds < chunk.start_seconds or segment.end_seconds > chunk.end_seconds:
                raise TranslationFailure(
                    code="invalid_chunk_output",
                    message=f"ASR segment {segment.id} does not fit inside media chunk {chunk.id}.",
                )
            current.append(segment)
            segment_offset += 1
        partitioned.append((chunk, current))
    if segment_offset != len(segments):
        raise TranslationFailure(
            code="invalid_chunk_output",
            message="ASR transcript contains segments outside the validated media chunk timeline.",
        )
    return partitioned


def _translate_media_chunks(
    session: Session,
    *,
    task_id: str,
    work_dir: Path,
    provider: TranslationProvider,
    chunk_segments: list[tuple[MediaChunk, list[SubtitleSegment]]],
) -> list[str]:
    """Translate reusable chunk-local results in source order and flatten their diagnostics."""
    translated_texts: list[str] = []
    total_chunks = len(chunk_segments)
    for completed_count, (chunk, source_segments) in enumerate(chunk_segments, start=1):
        cached_texts = _load_valid_translation_chunk(
            work_dir=work_dir,
            chunk=chunk,
            source_segments=source_segments,
            provider_metadata=dict(provider.metadata),
        )
        if cached_texts is None:
            candidate_texts = provider.translate_segments(source_segments)
            _validate_provider_translations(
                candidate_texts,
                source_segments=source_segments,
                provider_metadata=dict(provider.metadata),
            )
            _write_translation_chunk_atomically(
                work_dir=work_dir,
                chunk=chunk,
                source_segments=source_segments,
                translated_texts=candidate_texts,
                provider_metadata=dict(provider.metadata),
            )
            cached_texts = candidate_texts
        translated_texts.extend(cached_texts)
        _record_translation_chunk_progress(
            session,
            task_id=task_id,
            completed_count=completed_count,
            total_count=total_chunks,
            chunk_index=chunk.index,
        )
    if len(translated_texts) != sum(len(source_segments) for _, source_segments in chunk_segments):
        raise TranslationFailure(code="translation_failed", message="Merged translation chunk count does not match ASR segments.")
    return translated_texts


def _translation_chunk_path(*, work_dir: Path, chunk: MediaChunk) -> Path:
    return work_dir / TRANSLATION_CHUNK_DIRECTORY / f"{chunk.id}.json"


def _load_valid_translation_chunk(
    *,
    work_dir: Path,
    chunk: MediaChunk,
    source_segments: list[SubtitleSegment],
    provider_metadata: dict[str, object],
) -> list[str] | None:
    """Return a cache hit only when the exact global ASR rows are present and unchanged."""
    chunk_path = _translation_chunk_path(work_dir=work_dir, chunk=chunk)
    try:
        payload = json.loads(chunk_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != TRANSLATION_CHUNK_SCHEMA_VERSION:
        return None
    if payload.get("chunk_id") != chunk.id or payload.get("chunk_index") != chunk.index:
        return None
    if payload.get("provider_metadata") != provider_metadata:
        return None
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or len(raw_segments) != len(source_segments):
        return None
    texts: list[str] = []
    for raw_segment, source_segment in zip(raw_segments, source_segments, strict=True):
        if not isinstance(raw_segment, dict):
            return None
        if raw_segment.get("source") != _serialize_segment(source_segment):
            return None
        translated_text = raw_segment.get("translated_text")
        if not isinstance(translated_text, str) or not translated_text.strip():
            return None
        texts.append(translated_text.strip())
    return texts


def _write_translation_chunk_atomically(
    *,
    work_dir: Path,
    chunk: MediaChunk,
    source_segments: list[SubtitleSegment],
    translated_texts: list[str],
    provider_metadata: dict[str, object],
) -> Path:
    """Persist an exact source-to-translation chunk mapping without partial files."""
    chunk_path = _translation_chunk_path(work_dir=work_dir, chunk=chunk)
    payload = {
        "schema_version": TRANSLATION_CHUNK_SCHEMA_VERSION,
        "chunk_id": chunk.id,
        "chunk_index": chunk.index,
        "provider_metadata": provider_metadata,
        "segments": [
            {"source": _serialize_segment(segment), "translated_text": translated_text.strip()}
            for segment, translated_text in zip(source_segments, translated_texts, strict=True)
        ],
    }
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=chunk_path.parent, prefix=f".{chunk_path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        Path(temporary_name).replace(chunk_path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return chunk_path


def _serialize_segment(segment: SubtitleSegment) -> dict[str, object]:
    return {
        "id": segment.id,
        "start_seconds": segment.start_seconds,
        "end_seconds": segment.end_seconds,
        "text": segment.text,
        "words": [
            {
                "text": word.text,
                "start_seconds": word.start_seconds,
                "end_seconds": word.end_seconds,
                "confidence": word.confidence,
            }
            for word in segment.words
        ]
        if segment.words is not None
        else None,
    }


def _validate_provider_translations(
    translated_texts: list[str],
    *,
    source_segments: list[SubtitleSegment],
    provider_metadata: dict[str, object],
) -> None:
    if len(translated_texts) != len(source_segments):
        raise TranslationFailure(
            code="translation_failed",
            message=(
                f"Translation provider '{provider_metadata.get('model_name')}' returned "
                f"{len(translated_texts)} segments for {len(source_segments)} source segments."
            ),
        )
    for segment, translated_text in zip(source_segments, translated_texts, strict=True):
        if not isinstance(translated_text, str) or not translated_text.strip():
            raise TranslationFailure(
                code="translation_failed",
                message=(
                    f"Translation provider '{provider_metadata.get('model_name')}' returned an empty result "
                    f"for segment {segment.id}."
                ),
            )


def _record_translation_chunk_progress(
    session: Session,
    *,
    task_id: str,
    completed_count: int,
    total_count: int,
    chunk_index: int,
) -> None:
    summary = f"Translation {completed_count}/{total_count}"
    set_stage_status(session, task_id=task_id, stage_name="translation", status="running", summary=summary)
    upsert_task_execution_progress(
        session,
        task_id=task_id,
        stage_name="translation",
        current_phase="chunk",
        phase_index=completed_count,
        phase_count=total_count,
        latest_message=summary,
        phase_started_at=None,
        heartbeat_at=None,
        phase_timings=[{"name": f"chunk-{chunk_index:04d}", "status": "success", "elapsed_ms": None}],
    )
    session.commit()


def _record_translation_merge_progress(session: Session, *, task_id: str, total_count: int) -> None:
    """Expose a non-sensitive merge substep after every translation chunk has validated."""
    summary = "Translation merge"
    set_stage_status(session, task_id=task_id, stage_name="translation", status="running", summary=summary)
    upsert_task_execution_progress(
        session,
        task_id=task_id,
        stage_name="translation",
        current_phase="merge",
        phase_index=total_count,
        phase_count=total_count,
        latest_message=summary,
        phase_started_at=None,
        heartbeat_at=None,
        phase_timings=[{"name": "merge", "status": "running", "elapsed_ms": None}],
    )
    session.commit()


def _record_translation_proofread_progress(session: Session, *, task_id: str, total_count: int) -> None:
    """Expose the required final text-only review without exposing provider payloads."""
    summary = "Translation proofread"
    set_stage_status(session, task_id=task_id, stage_name="translation", status="running", summary=summary)
    upsert_task_execution_progress(
        session,
        task_id=task_id,
        stage_name="translation",
        current_phase="proofread",
        phase_index=total_count,
        phase_count=total_count,
        latest_message=summary,
        phase_started_at=None,
        heartbeat_at=None,
        phase_timings=[{"name": "proofread", "status": "running", "elapsed_ms": None}],
    )
    session.commit()


def _classify_translation_exception(
    exc: Exception,
    *,
    provider_metadata: dict[str, object],
    settings: Settings,
) -> TranslationFailure:
    if isinstance(exc, TranslationFailure):
        return exc
    if isinstance(exc, ProofreadFailure):
        code_by_provider_code = {
            "missing_api_key": "translation_proofread_missing_api_key",
            "proofread_auth_failed": "translation_proofread_auth_failed",
            "proofread_billing_failed": "translation_proofread_billing_failed",
            "proofread_rate_limit": "translation_proofread_rate_limit",
            "proofread_timeout": "translation_proofread_timeout",
            "proofread_transient_exhausted": "translation_proofread_transient_exhausted",
            "proofread_invalid_response": "translation_proofread_invalid_response",
            "proofread_http_error": "translation_proofread_http_error",
        }
        return TranslationFailure(
            code=code_by_provider_code.get(exc.code, "translation_proofread_failed"),
            message=exc.message,
        )

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
