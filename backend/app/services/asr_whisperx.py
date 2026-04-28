from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.paths import get_data_dir
from app.repositories.tasks import get_task_record
from app.services.pipeline_support import append_stage_log, set_stage_status
from app.services.storage import ensure_task_dirs, log_file_for_stage, persist_artifact_metadata
from app.services.subtitles import SubtitleSegment, SubtitleWord, write_subtitle_outputs
from app.settings import Settings, get_settings

snapshot_download: Any | None = None
download_faster_whisper_model: Any | None = None


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


def _default_model_root(settings: Settings) -> Path:
    cache_dir = settings.whisperx_model_cache_dir
    if cache_dir is not None:
        return cache_dir
    return get_data_dir() / "models" / "whisperx"


def _model_target_dir(*, root: Path, key: str) -> Path:
    return root / key


def _main_model_target_dir(settings: Settings) -> Path:
    return _model_target_dir(root=_default_model_root(settings), key="whisperx")


def _alignment_model_target_dir(settings: Settings) -> Path:
    return _model_target_dir(root=_default_model_root(settings), key="alignment")


def _alignment_repo_id(settings: Settings) -> str:
    if settings.whisperx_alignment_model_name:
        return settings.whisperx_alignment_model_name
    if settings.whisperx_language == "zh":
        return "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn"
    return ""


def _is_main_model_ready(target_dir: Path) -> bool:
    return target_dir.is_dir() and (target_dir / "config.json").exists() and (target_dir / "model.bin").exists()


def _is_alignment_model_ready(target_dir: Path) -> bool:
    return target_dir.is_dir() and (target_dir / "config.json").exists()


def _resolve_main_model_ref(settings: Settings) -> str:
    target_dir = _main_model_target_dir(settings)
    if _is_main_model_ready(target_dir):
        return str(target_dir)
    return str(settings.whisperx_model_name)


def _resolve_alignment_model_ref(settings: Settings) -> str | None:
    target_dir = _alignment_model_target_dir(settings)
    if _is_alignment_model_ready(target_dir):
        return str(target_dir)
    if settings.whisperx_alignment_model_name:
        return settings.whisperx_alignment_model_name
    return None


def _recovery_envelope(*, models: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "stage": "asr",
        "kind": "missing_model",
        "models": models,
    }


def build_asr_missing_model_recovery(settings: Settings) -> dict[str, Any]:
    main_target = _main_model_target_dir(settings)
    align_target = _alignment_model_target_dir(settings)
    alignment_repo_id = _alignment_repo_id(settings)

    return {
        "stage": "asr",
        "kind": "missing_model",
        "message": "ASR 缺少 WhisperX 模型文件。你可以让程序自动下载，或按下面目录手动放置。",
        "models": [
            {
                "key": "whisperx",
                "label": "WhisperX 主模型",
                "status": "ready" if _is_main_model_ready(main_target) else "missing",
                "target_dir": str(main_target),
                "repo_id": str(settings.whisperx_model_name),
                "download_supported": True,
            },
            {
                "key": "alignment",
                "label": "Alignment 模型",
                "status": "ready" if _is_alignment_model_ready(align_target) else "missing",
                "target_dir": str(align_target),
                "repo_id": alignment_repo_id,
                "download_supported": bool(alignment_repo_id),
            },
        ],
    }


def download_asr_missing_models(settings: Settings, *, requested_keys: list[str]) -> dict[str, Any]:
    recovery = build_asr_missing_model_recovery(settings)
    models = [
        _resolve_requested_model_download(model, requested_keys=requested_keys)
        for model in recovery["models"]
        if model["key"] in requested_keys
    ]
    return _recovery_envelope(models=models)


def _resolve_requested_model_download(model: dict[str, Any], *, requested_keys: list[str]) -> dict[str, Any]:
    item = dict(model)
    if not _should_attempt_model_download(item, requested_keys=requested_keys):
        return item

    repo_id = item.get("repo_id")
    if not repo_id:
        item["download_supported"] = False
        return item

    try:
        _download_requested_model(item)
    except Exception:
        return item

    item["status"] = "downloaded"
    return item


def _should_attempt_model_download(model: dict[str, Any], *, requested_keys: list[str]) -> bool:
    return model["key"] in requested_keys and model["status"] != "ready"


def _download_model_snapshot(*, repo_id: str, target_dir: str) -> None:
    global snapshot_download

    if snapshot_download is None:
        from huggingface_hub import snapshot_download as huggingface_snapshot_download

        snapshot_download = huggingface_snapshot_download

    snapshot_download(repo_id=repo_id, local_dir=target_dir, local_dir_use_symlinks=False)


def _download_main_model(*, model_ref: str, target_dir: str) -> None:
    global download_faster_whisper_model

    if download_faster_whisper_model is None:
        from faster_whisper.utils import download_model as faster_whisper_download_model

        download_faster_whisper_model = faster_whisper_download_model

    download_faster_whisper_model(model_ref, output_dir=target_dir)


def _download_requested_model(model: dict[str, Any]) -> None:
    if model["key"] == "whisperx":
        _download_main_model(model_ref=model["repo_id"], target_dir=model["target_dir"])
        return
    _download_model_snapshot(repo_id=model["repo_id"], target_dir=model["target_dir"])


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
            _resolve_main_model_ref(settings),
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
            model_name=_resolve_alignment_model_ref(settings),
            model_dir=str(_alignment_model_target_dir(settings)),
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
