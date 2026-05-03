from __future__ import annotations

import importlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

from sqlmodel import Session

from app.paths import get_data_dir
from app.repositories.tasks import get_task_record
from app.services.pipeline_support import append_stage_log, set_stage_status
from app.services.storage import (
    ensure_task_dirs,
    log_file_for_stage,
    persist_artifact_metadata,
    resolve_task_artifact_path,
)
from app.services.subtitles import SubtitleSegment, SubtitleWord, write_subtitle_outputs
from app.settings import Settings, get_settings

snapshot_download: Any | None = None
download_faster_whisper_model: Any | None = None
ASR_STAGE_SUCCESS_SUMMARY = "Generated aligned transcript and Chinese subtitles"


@dataclass(slots=True)
class AsrStageResult:
    audio_path: Path
    transcript_path: Path
    subtitle_path: Path
    raw_alignment_path: Path
    model_metadata: dict[str, Any]
    elapsed_seconds: float
    segments: list[SubtitleSegment]


@dataclass(slots=True)
class AsrPhaseResult:
    name: str
    status: str
    elapsed_ms: int | None = None


@dataclass(slots=True)
class AsrPipelineResult:
    audio_path: Path
    transcript_path: Path
    subtitle_path: Path
    raw_alignment_path: Path
    model_metadata: dict[str, Any]
    elapsed_seconds: float
    elapsed_ms_total: int
    segments: list[SubtitleSegment]
    phases: list[AsrPhaseResult]


@dataclass(slots=True)
class AsrResultManifest:
    status: str
    elapsed_ms_total: int
    phases: list[AsrPhaseResult]
    artifacts: AsrArtifactPaths
    model_metadata: dict[str, Any]
    error: dict[str, Any] | None


class AsrFailure(RuntimeError):
    def __init__(self, *, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class AsrArtifactPaths:
    audio_path: Path
    transcript_path: Path | None
    subtitle_path: Path | None
    raw_alignment_path: Path | None


class AsrPipelineError(AsrFailure):
    def __init__(
        self,
        *,
        failure: AsrFailure,
        phase: str,
        phases: list[AsrPhaseResult],
        elapsed_ms_total: int,
        model_metadata: dict[str, Any],
        artifacts: AsrArtifactPaths,
    ):
        super().__init__(code=failure.code, message=str(failure))
        self.phase = phase
        self.phases = phases
        self.elapsed_ms_total = elapsed_ms_total
        self.model_metadata = model_metadata
        self.artifacts = artifacts


class AsrPipelineObserver(Protocol):
    def phase_start(self, phase: str, *, phase_index: int, phase_count: int, message: str) -> None: ...

    def heartbeat(
        self,
        phase: str,
        *,
        phase_index: int,
        phase_count: int,
        elapsed_ms: int,
        message: str,
    ) -> None: ...

    def phase_complete(self, phase: str, *, phase_index: int, phase_count: int, elapsed_ms: int) -> None: ...


ASR_PIPELINE_PHASES = ("model_load", "vad", "transcribe", "align", "persist")
ASR_PIPELINE_PHASE_INDEX = {phase: index for index, phase in enumerate(ASR_PIPELINE_PHASES, start=1)}
ASR_PHASE_HEARTBEAT_INTERVAL_SECONDS = 0.1

_PhaseValue = TypeVar("_PhaseValue")


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
    try:
        pipeline_result = execute_asr_pipeline(
            audio_path=audio_path,
            work_dir=work_dir,
            settings=settings,
        )
    except AsrFailure as failure:
        append_stage_log(log_path, f"classified_failure={failure.code}")
        append_stage_log(log_path, str(failure))
        set_stage_status(session, task_id=task_id, stage_name="asr", status="failed", summary=failure.code)
        session.commit()
        raise

    _persist_asr_artifacts(
        session,
        task_id=task_id,
        audio_path=pipeline_result.audio_path,
        transcript_path=pipeline_result.transcript_path,
        subtitle_path=pipeline_result.subtitle_path,
        raw_alignment_path=pipeline_result.raw_alignment_path,
        model_metadata=pipeline_result.model_metadata,
        elapsed_seconds=pipeline_result.elapsed_seconds,
        segment_count=len(pipeline_result.segments),
        language=settings.whisperx_language,
    )
    set_stage_status(
        session,
        task_id=task_id,
        stage_name="asr",
        status="success",
        summary=ASR_STAGE_SUCCESS_SUMMARY,
    )
    return AsrStageResult(
        audio_path=pipeline_result.audio_path,
        transcript_path=pipeline_result.transcript_path,
        subtitle_path=pipeline_result.subtitle_path,
        raw_alignment_path=pipeline_result.raw_alignment_path,
        model_metadata=pipeline_result.model_metadata,
        elapsed_seconds=pipeline_result.elapsed_seconds,
        segments=pipeline_result.segments,
    )


def load_asr_result_manifest(manifest_path: Path) -> AsrResultManifest:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise AsrFailure(
            code="invalid_result_manifest",
            message=f"ASR child result manifest is unavailable or invalid: {manifest_path}",
        ) from exc
    if not isinstance(payload, dict):
        raise AsrFailure(
            code="invalid_result_manifest",
            message=f"ASR child result manifest must be an object: {manifest_path}",
        )

    status = str(payload.get("status") or "").strip() or "failed"
    try:
        elapsed_ms_total = max(0, int(payload.get("elapsed_ms_total") or 0))
    except (TypeError, ValueError):
        elapsed_ms_total = 0
    artifacts_payload = payload.get("artifacts")
    if not isinstance(artifacts_payload, dict):
        raise AsrFailure(
            code="invalid_result_manifest",
            message=f"ASR child result manifest is missing artifact paths: {manifest_path}",
        )
    model_metadata = payload.get("model_metadata")
    error = payload.get("error")
    return AsrResultManifest(
        status=status,
        elapsed_ms_total=elapsed_ms_total,
        phases=_deserialize_manifest_phases(payload.get("phases")),
        artifacts=AsrArtifactPaths(
            audio_path=Path(str(artifacts_payload.get("audio_path") or "")),
            transcript_path=_optional_manifest_path(artifacts_payload.get("transcript_path")),
            subtitle_path=_optional_manifest_path(artifacts_payload.get("subtitle_path")),
            raw_alignment_path=_optional_manifest_path(artifacts_payload.get("raw_alignment_path")),
        ),
        model_metadata=dict(model_metadata) if isinstance(model_metadata, dict) else {},
        error=dict(error) if isinstance(error, dict) else None,
    )


def publish_asr_artifacts_from_manifest(
    session: Session,
    *,
    task_id: str,
    manifest: AsrResultManifest,
) -> None:
    if manifest.status != "success":
        raise _manifest_error_to_failure(manifest)

    audio_path = _require_manifest_path(task_id, manifest.artifacts.audio_path, kind="audio_path")
    transcript_path = _require_manifest_path(task_id, manifest.artifacts.transcript_path, kind="transcript_path")
    subtitle_path = _require_manifest_path(task_id, manifest.artifacts.subtitle_path, kind="subtitle_path")
    raw_alignment_path = _require_manifest_path(
        task_id,
        manifest.artifacts.raw_alignment_path,
        kind="raw_alignment_path",
    )
    elapsed_seconds = round(manifest.elapsed_ms_total / 1000, 3)
    segment_count = _count_transcript_segments(transcript_path)
    _persist_asr_artifacts(
        session,
        task_id=task_id,
        audio_path=audio_path,
        transcript_path=transcript_path,
        subtitle_path=subtitle_path,
        raw_alignment_path=raw_alignment_path,
        model_metadata=manifest.model_metadata,
        elapsed_seconds=elapsed_seconds,
        segment_count=segment_count,
        language=str(manifest.model_metadata.get("language") or ""),
    )


def execute_asr_pipeline(
    *,
    audio_path: Path,
    work_dir: Path,
    settings: Settings,
    observer: AsrPipelineObserver | None = None,
) -> AsrPipelineResult:
    phase_results = {phase: AsrPhaseResult(name=phase, status="pending") for phase in ASR_PIPELINE_PHASES}
    raw_alignment_path = work_dir / "asr-alignment-raw.json"
    artifacts = AsrArtifactPaths(
        audio_path=audio_path,
        transcript_path=None,
        subtitle_path=None,
        raw_alignment_path=None,
    )
    model_metadata: dict[str, Any] = {}
    started_at = time.perf_counter()
    current_phase = ASR_PIPELINE_PHASES[0]

    try:
        _ensure_input_audio_path(audio_path)
        model_metadata = _build_model_metadata(settings)
        whisperx = _load_whisperx_module()
        model = _run_pipeline_phase(
            phase="model_load",
            phase_results=phase_results,
            observer=observer,
            action=lambda: whisperx.load_model(
                _resolve_main_model_ref(settings),
                settings.whisperx_device,
                compute_type=settings.whisperx_compute_type,
                download_root=str(settings.whisperx_model_cache_dir) if settings.whisperx_model_cache_dir else None,
            ),
        )

        current_phase = "vad"
        _run_pipeline_phase(
            phase="vad",
            phase_results=phase_results,
            observer=observer,
            action=lambda: None,
        )

        current_phase = "transcribe"
        transcription_result = _run_pipeline_phase(
            phase="transcribe",
            phase_results=phase_results,
            observer=observer,
            action=lambda: model.transcribe(
                str(audio_path),
                batch_size=settings.whisperx_batch_size,
                language=settings.whisperx_language,
            ),
        )
        language_code = transcription_result.get("language") or settings.whisperx_language

        current_phase = "align"
        aligned_result = _run_pipeline_phase(
            phase="align",
            phase_results=phase_results,
            observer=observer,
            action=lambda: _align_transcription_result(
                whisperx=whisperx,
                transcription_result=transcription_result,
                audio_path=audio_path,
                settings=settings,
                language_code=language_code,
            ),
        )
        segments = _normalize_aligned_segments(aligned_result.get("segments"))

        current_phase = "persist"
        output_elapsed_seconds = round(_elapsed_ms(started_at) / 1000, 3)
        transcript_path, subtitle_path = _run_pipeline_phase(
            phase="persist",
            phase_results=phase_results,
            observer=observer,
            action=lambda: _persist_asr_outputs(
                work_dir=work_dir,
                raw_alignment_path=raw_alignment_path,
                aligned_result=aligned_result,
                segments=segments,
                model_metadata=model_metadata,
                elapsed_seconds=output_elapsed_seconds,
            ),
        )
        artifacts.raw_alignment_path = raw_alignment_path
        artifacts.transcript_path = transcript_path
        artifacts.subtitle_path = subtitle_path
        elapsed_ms_total = _elapsed_ms(started_at)
        return AsrPipelineResult(
            audio_path=audio_path,
            transcript_path=transcript_path,
            subtitle_path=subtitle_path,
            raw_alignment_path=raw_alignment_path,
            model_metadata=model_metadata,
            elapsed_seconds=output_elapsed_seconds,
            elapsed_ms_total=elapsed_ms_total,
            segments=segments,
            phases=list(phase_results.values()),
        )
    except Exception as exc:
        failure = _classify_asr_exception(exc, settings=settings)
        failed_phase = _resolve_failed_phase(phase_results, fallback=current_phase)
        _mark_failed_phase(phase_results, failed_phase)
        raise AsrPipelineError(
            failure=failure,
            phase=failed_phase,
            phases=list(phase_results.values()),
            elapsed_ms_total=_elapsed_ms(started_at),
            model_metadata=model_metadata,
            artifacts=artifacts,
        ) from exc


def _ensure_input_audio_path(audio_path: Path) -> None:
    if audio_path.exists():
        return
    raise AsrFailure(
        code="missing_input",
        message="ASR input WAV is missing. Re-run media preparation or restore the normalized audio artifact before retrying.",
    )


def _align_transcription_result(
    *,
    whisperx,
    transcription_result: dict[str, Any],
    audio_path: Path,
    settings: Settings,
    language_code: str,
) -> dict[str, Any]:
    align_model, align_metadata = whisperx.load_align_model(
        language_code=language_code,
        device=settings.whisperx_device,
        model_name=_resolve_alignment_model_ref(settings),
        model_dir=str(_alignment_model_target_dir(settings)),
    )
    return whisperx.align(
        transcription_result.get("segments") or [],
        align_model,
        align_metadata,
        str(audio_path),
        settings.whisperx_device,
        return_char_alignments=False,
    )


def _persist_asr_outputs(
    *,
    work_dir: Path,
    raw_alignment_path: Path,
    aligned_result: dict[str, Any],
    segments: list[SubtitleSegment],
    model_metadata: dict[str, Any],
    elapsed_seconds: float,
) -> tuple[Path, Path]:
    raw_alignment_path.write_text(
        json.dumps(aligned_result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return write_subtitle_outputs(
        work_dir,
        segments,
        model_metadata=model_metadata,
        elapsed_seconds=elapsed_seconds,
    )


def _persist_asr_artifacts(
    session: Session,
    *,
    task_id: str,
    audio_path: Path,
    transcript_path: Path,
    subtitle_path: Path,
    raw_alignment_path: Path,
    model_metadata: dict[str, Any],
    elapsed_seconds: float,
    segment_count: int,
    language: str,
) -> None:
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
    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="asr",
        kind="transcript_json",
        path=transcript_path,
        metadata={
            "elapsed_seconds": elapsed_seconds,
            "model_metadata": model_metadata,
            "segment_count": segment_count,
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
            "segment_count": segment_count,
            "language": language,
        },
    )


def _deserialize_manifest_phases(raw_phases: Any) -> list[AsrPhaseResult]:
    if not isinstance(raw_phases, list):
        return []
    phases: list[AsrPhaseResult] = []
    for raw_phase in raw_phases:
        if not isinstance(raw_phase, dict):
            continue
        elapsed_ms = raw_phase.get("elapsed_ms")
        if not isinstance(elapsed_ms, int):
            elapsed_ms = None
        phases.append(
            AsrPhaseResult(
                name=str(raw_phase.get("name") or "").strip() or "unknown",
                status=str(raw_phase.get("status") or "pending").strip() or "pending",
                elapsed_ms=elapsed_ms,
            )
        )
    return phases


def _optional_manifest_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def _require_manifest_path(task_id: str, path: Path | None, *, kind: str) -> Path:
    if path is None:
        raise AsrFailure(
            code="invalid_result_manifest",
            message=f"ASR child result manifest is missing {kind}.",
        )
    try:
        resolved = resolve_task_artifact_path(task_id, path)
    except Exception as exc:
        raise AsrFailure(
            code="invalid_result_manifest",
            message=f"ASR child result manifest referenced an unsafe {kind}: {path}",
        ) from exc
    if not resolved.exists():
        raise AsrFailure(
            code="invalid_result_manifest",
            message=f"ASR child result manifest referenced a missing {kind}: {resolved}",
        )
    return resolved


def _count_transcript_segments(transcript_path: Path) -> int:
    try:
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise AsrFailure(
            code="invalid_result_manifest",
            message=f"ASR transcript artifact is unavailable or invalid: {transcript_path}",
        ) from exc
    segments = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(segments, list):
        raise AsrFailure(
            code="invalid_result_manifest",
            message=f"ASR transcript artifact is missing segments: {transcript_path}",
        )
    return len(segments)


def _manifest_error_to_failure(manifest: AsrResultManifest) -> AsrFailure:
    error = manifest.error or {}
    code = str(error.get("code") or "asr_child_failed").strip() or "asr_child_failed"
    message = str(error.get("message") or "ASR child reported failure.").strip() or "ASR child reported failure."
    return AsrFailure(code=code, message=message)


def _run_pipeline_phase(
    *,
    phase: str,
    phase_results: dict[str, AsrPhaseResult],
    observer: AsrPipelineObserver | None,
    action: Callable[[], _PhaseValue],
) -> _PhaseValue:
    phase_result = phase_results[phase]
    phase_result.status = "running"
    phase_result.elapsed_ms = None
    phase_index = ASR_PIPELINE_PHASE_INDEX[phase]
    phase_count = len(ASR_PIPELINE_PHASES)
    started_at = time.perf_counter()
    heartbeat_stop: threading.Event | None = None
    heartbeat_thread: threading.Thread | None = None
    if observer is not None:
        observer.phase_start(
            phase,
            phase_index=phase_index,
            phase_count=phase_count,
            message=f"starting {phase}",
        )
        observer.heartbeat(
            phase,
            phase_index=phase_index,
            phase_count=phase_count,
            elapsed_ms=0,
            message=f"{phase} running",
        )

        def _emit_heartbeats() -> None:
            assert heartbeat_stop is not None
            while not heartbeat_stop.wait(ASR_PHASE_HEARTBEAT_INTERVAL_SECONDS):
                observer.heartbeat(
                    phase,
                    phase_index=phase_index,
                    phase_count=phase_count,
                    elapsed_ms=_elapsed_ms(started_at),
                    message=f"{phase} running",
                )

        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(target=_emit_heartbeats, daemon=True)
        heartbeat_thread.start()
    try:
        value = action()
    except Exception:
        phase_result.status = "failed"
        phase_result.elapsed_ms = _elapsed_ms(started_at)
        raise
    finally:
        if heartbeat_stop is not None:
            heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=ASR_PHASE_HEARTBEAT_INTERVAL_SECONDS * 2)
    phase_result.status = "success"
    phase_result.elapsed_ms = _elapsed_ms(started_at)
    if observer is not None:
        observer.phase_complete(
            phase,
            phase_index=phase_index,
            phase_count=phase_count,
            elapsed_ms=phase_result.elapsed_ms or 0,
        )
    return value


def _resolve_failed_phase(phase_results: dict[str, AsrPhaseResult], *, fallback: str) -> str:
    for phase in ASR_PIPELINE_PHASES:
        if phase_results[phase].status in {"failed", "running"}:
            return phase
    return fallback


def _mark_failed_phase(phase_results: dict[str, AsrPhaseResult], phase: str) -> None:
    phase_result = phase_results[phase]
    if phase_result.status != "pending":
        return
    phase_result.status = "failed"


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


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
