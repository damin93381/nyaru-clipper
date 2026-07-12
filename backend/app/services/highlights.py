from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import ClipCandidate
from app.repositories.tasks import get_task_record
from app.services.highlight_scoring import (
    AudioEnergyWindow,
    MIN_CANDIDATE_SCORE,
    SceneWindow,
    derive_scene_like_windows,
    score_candidate_windows,
)
from app.services.pipeline_support import append_stage_log, set_stage_status
from app.services.scene_detection import SceneDetectionProvider, build_scene_detection_provider
from app.services.source_catalog import resolve_local_reference_artifact
from app.services.storage import ensure_task_dirs, log_file_for_stage, persist_artifact_metadata
from app.services.subtitles import SubtitleSegment, SubtitleWord

NO_CANDIDATES_EXPLANATION = (
    "No highlight candidates cleared the minimum score threshold from the available scene and subtitle signals."
)


@dataclass(slots=True)
class HighlightStageResult:
    transcript_path: Path
    scene_path: Path | None
    artifact_path: Path
    elapsed_seconds: float
    candidates: list[dict[str, Any]]
    no_candidates: str | None


class HighlightFailure(RuntimeError):
    def __init__(self, *, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class SceneBoundaryResolution:
    scene_windows: list[SceneWindow]
    scene_path: Path | None
    artifact_kind: str | None
    metadata: dict[str, Any]


def analyze_task_highlights(
    session: Session,
    task_id: str,
    *,
    scene_windows: list[SceneWindow] | None = None,
    scene_detection_provider: SceneDetectionProvider | None = None,
    audio_energy_windows: list[AudioEnergyWindow] | None = None,
) -> HighlightStageResult:
    record = get_task_record(session, task_id)
    if record is None:
        raise ValueError(f"Unknown task_id: {task_id}")

    task_dirs = ensure_task_dirs(task_id)
    log_path = log_file_for_stage(task_id, "highlight")
    transcript_path = _resolve_transcript_path(task_id, record)
    subtitle_segments = _load_segments_from_transcript(transcript_path)

    append_stage_log(log_path, f"highlight_input={transcript_path}")

    started_at = time.perf_counter()
    try:
        scene_resolution = _resolve_scene_boundaries(
            session,
            task_id,
            record,
            subtitle_segments,
            log_path=log_path,
            scene_windows=scene_windows,
            scene_detection_provider=scene_detection_provider,
        )
        effective_scene_windows = scene_resolution.scene_windows
        scene_path = scene_resolution.scene_path
        append_stage_log(log_path, f"scene_input={scene_path or 'injected_scene_windows'}")
        effective_audio_windows = audio_energy_windows or _load_audio_energy_windows(task_id, record)
        candidates = score_candidate_windows(
            effective_scene_windows,
            subtitle_segments,
            audio_energy_windows=effective_audio_windows,
            media_end_s=max((segment.end_seconds for segment in subtitle_segments), default=None),
            min_score=MIN_CANDIDATE_SCORE,
        )
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        no_candidates = None if candidates else NO_CANDIDATES_EXPLANATION
    except Exception as exc:
        failure = _classify_highlight_exception(exc)
        append_stage_log(log_path, f"classified_failure={failure.code}")
        append_stage_log(log_path, str(failure))
        set_stage_status(session, task_id=task_id, stage_name="highlight", status="failed", summary=failure.code)
        session.commit()
        raise failure from exc

    _replace_existing_candidates(session, task_id)
    persisted_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        clip_candidate = ClipCandidate(
            task_id=task_id,
            start_seconds=float(candidate["start_s"]),
            end_seconds=float(candidate["end_s"]),
            score=float(candidate["score"]),
            reason=",".join(candidate["reasons"]),
            status=str(candidate["status"]),
        )
        session.add(clip_candidate)
        session.flush()
        persisted_candidate = dict(candidate)
        persisted_candidate["candidate_id"] = clip_candidate.id
        persisted_candidates.append(persisted_candidate)

    artifact_path = _write_candidate_artifact(
        task_dirs["work"] / "highlight-candidates.json",
        transcript_path=transcript_path,
        scene_path=scene_path,
        elapsed_seconds=elapsed_seconds,
        candidates=persisted_candidates,
        no_candidates=no_candidates,
    )

    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="highlight",
        kind="highlight_candidates_json",
        path=artifact_path,
        metadata={
            "candidate_count": len(candidates),
            "elapsed_seconds": elapsed_seconds,
            "no_candidates": no_candidates,
            "transcript_path": str(transcript_path),
            "scene_path": str(scene_path) if scene_path is not None else None,
            "scene_count": len(effective_scene_windows),
            "scene_artifact_kind": scene_resolution.artifact_kind,
            "scene_metadata": scene_resolution.metadata,
        },
    )

    summary = no_candidates or f"Ranked {len(candidates)} highlight candidate windows"
    set_stage_status(session, task_id=task_id, stage_name="highlight", status="success", summary=summary)

    return HighlightStageResult(
        transcript_path=transcript_path,
        scene_path=scene_path,
        artifact_path=artifact_path,
        elapsed_seconds=elapsed_seconds,
        candidates=candidates,
        no_candidates=no_candidates,
    )


def _replace_existing_candidates(session: Session, task_id: str) -> None:
    existing_candidates = session.exec(select(ClipCandidate).where(ClipCandidate.task_id == task_id)).all()
    for candidate in existing_candidates:
        session.delete(candidate)
    session.flush()


def _resolve_transcript_path(task_id: str, record) -> Path:
    task_dirs = ensure_task_dirs(task_id)
    preferred_paths = [task_dirs["work"] / "subtitles.zh-ja.json", task_dirs["work"] / "asr-segments.json"]
    for preferred in preferred_paths:
        if preferred.exists():
            return preferred

    for artifact in reversed(record.artifacts):
        if artifact.stage_name == "translation" and artifact.kind == "bilingual_transcript_json":
            candidate = Path(artifact.path)
            if candidate.exists():
                return candidate
        if artifact.stage_name == "asr" and artifact.kind == "transcript_json":
            candidate = Path(artifact.path)
            if candidate.exists():
                return candidate

    raise HighlightFailure(
        code="missing_input",
        message="Highlight analysis requires translated subtitle JSON or ASR transcript JSON before it can score candidate windows.",
    )


def _resolve_scene_path(task_id: str, record) -> Path | None:
    task_dirs = ensure_task_dirs(task_id)
    preferred_paths = [task_dirs["work"] / "scene-boundaries.json", task_dirs["work"] / "scene-like-boundaries.json"]
    for preferred in preferred_paths:
        if preferred.exists():
            return preferred

    for artifact in reversed(record.artifacts):
        if artifact.kind in {"scene_boundaries_json", "scene_like_boundaries_json"}:
            candidate = Path(artifact.path)
            if candidate.exists():
                return candidate
    return None


def _resolve_scene_boundaries(
    session: Session,
    task_id: str,
    record,
    subtitle_segments: list[SubtitleSegment],
    *,
    log_path: Path,
    scene_windows: list[SceneWindow] | None,
    scene_detection_provider: SceneDetectionProvider | None,
) -> SceneBoundaryResolution:
    if scene_windows:
        append_stage_log(log_path, "scene_detection=injected")
        return SceneBoundaryResolution(
            scene_windows=list(scene_windows),
            scene_path=None,
            artifact_kind=None,
            metadata={"source": "injected", "scene_count": len(scene_windows)},
        )

    scene_path = _resolve_scene_path(task_id, record)
    if scene_path is not None:
        loaded_scene_windows = _load_scene_windows(scene_path, subtitle_segments)
        append_stage_log(log_path, f"scene_detection=artifact:{scene_path}")
        return SceneBoundaryResolution(
            scene_windows=loaded_scene_windows,
            scene_path=scene_path,
            artifact_kind=_scene_artifact_kind_for_path(record, scene_path),
            metadata={"source": "artifact", "scene_count": len(loaded_scene_windows)},
        )

    return _detect_or_derive_scene_boundaries(
        session,
        task_id,
        record,
        subtitle_segments,
        log_path=log_path,
        scene_detection_provider=scene_detection_provider,
    )


def _detect_or_derive_scene_boundaries(
    session: Session,
    task_id: str,
    record,
    subtitle_segments: list[SubtitleSegment],
    *,
    log_path: Path,
    scene_detection_provider: SceneDetectionProvider | None,
) -> SceneBoundaryResolution:
    task_dirs = ensure_task_dirs(task_id)
    detected_scene_windows: list[SceneWindow] = []
    source_video_path: Path | None = None
    source_reference: str | None = None
    provider_metadata: dict[str, object] = {}
    fallback_reason: str | None = None

    try:
        source_video_path = _resolve_source_video_path(task_id, record)
        source_reference = _source_video_reference(record, source_video_path)
        provider = scene_detection_provider or build_scene_detection_provider()
        provider_metadata = dict(provider.metadata)
        append_stage_log(log_path, f"scene_detection_input={source_reference}")
        append_stage_log(log_path, f"scene_detection_provider={provider_metadata.get('provider')}")
        detected_scene_windows = provider.detect_scenes(source_video_path)
    except Exception as exc:
        fallback_reason = _safe_source_text(str(exc).strip() or exc.__class__.__name__, source_video_path, source_reference)
    else:
        if detected_scene_windows:
            scene_path = _write_scene_artifact(
                task_dirs["work"] / "scene-boundaries.json",
                source="pyscenedetect",
                source_video_reference=source_reference,
                scene_windows=detected_scene_windows,
                provider_metadata=provider_metadata,
                fallback_reason=None,
            )
            metadata = {
                "scene_count": len(detected_scene_windows),
                "provider_metadata": provider_metadata,
                "source_video_path": source_reference,
            }
            persist_artifact_metadata(
                session,
                task_id=task_id,
                stage_name="highlight",
                kind="scene_boundaries_json",
                path=scene_path,
                metadata=metadata,
            )
            append_stage_log(log_path, f"scene_detection=provider scene_count={len(detected_scene_windows)}")
            return SceneBoundaryResolution(
                scene_windows=detected_scene_windows,
                scene_path=scene_path,
                artifact_kind="scene_boundaries_json",
                metadata=metadata,
            )
        fallback_reason = "PySceneDetect returned no usable scenes."

    append_stage_log(log_path, f"scene_detection_fallback={fallback_reason}")
    fallback_scene_windows = derive_scene_like_windows(subtitle_segments)
    fallback_path = _write_scene_artifact(
        task_dirs["work"] / "scene-like-boundaries.json",
        source="subtitle_gap_fallback",
        source_video_reference=source_reference,
        scene_windows=fallback_scene_windows,
        provider_metadata=provider_metadata,
        fallback_reason=fallback_reason,
    )
    fallback_metadata = {
        "scene_count": len(fallback_scene_windows),
        "provider_metadata": provider_metadata,
        "source_video_path": source_reference,
        "fallback_reason": fallback_reason,
    }
    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="highlight",
        kind="scene_like_boundaries_json",
        path=fallback_path,
        metadata=fallback_metadata,
    )
    return SceneBoundaryResolution(
        scene_windows=fallback_scene_windows,
        scene_path=fallback_path,
        artifact_kind="scene_like_boundaries_json",
        metadata=fallback_metadata,
    )


def _resolve_source_video_path(task_id: str, record) -> Path:
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
    raise FileNotFoundError("Source video artifact is missing for scene detection.")


def _source_video_reference(record, source_video_path: Path) -> str:
    """Use an opaque local locator in artifacts and logs while retaining a runtime path for processing."""
    for artifact in reversed(record.artifacts):
        if artifact.stage_name != "ingest" or artifact.kind != "source_video":
            continue
        local_source = resolve_local_reference_artifact(artifact.metadata_json)
        if local_source is not None:
            return local_source.locator
    return str(source_video_path)


def _safe_source_text(value: str, source_video_path: Path | None, source_reference: str | None) -> str:
    """Replace a runtime-only local path in diagnostics before they become durable metadata or logs."""
    if source_video_path is None or source_reference is None:
        return value
    return value.replace(str(source_video_path), source_reference)


def _scene_artifact_kind_for_path(record, scene_path: Path) -> str | None:
    for artifact in reversed(record.artifacts):
        if artifact.path == str(scene_path) and artifact.kind in {"scene_boundaries_json", "scene_like_boundaries_json"}:
            return artifact.kind
    if scene_path.name == "scene-boundaries.json":
        return "scene_boundaries_json"
    if scene_path.name == "scene-like-boundaries.json":
        return "scene_like_boundaries_json"
    return None


def _load_scene_windows(scene_path: Path | None, subtitle_segments: list[SubtitleSegment]) -> list[SceneWindow]:
    if scene_path is None:
        return derive_scene_like_windows(subtitle_segments)

    payload = json.loads(scene_path.read_text(encoding="utf-8"))
    raw_scenes = payload.get("scenes") if isinstance(payload, dict) else payload
    if not isinstance(raw_scenes, list):
        raise HighlightFailure(code="missing_input", message="Scene boundary input is invalid or missing the 'scenes' list.")

    scene_windows: list[SceneWindow] = []
    for index, raw_scene in enumerate(raw_scenes, start=1):
        if not isinstance(raw_scene, dict):
            raise HighlightFailure(code="missing_input", message="Scene boundary input contains an invalid scene payload.")
        start_s = float(raw_scene["start_s"])
        end_s = float(raw_scene["end_s"])
        if end_s <= start_s:
            raise HighlightFailure(code="missing_input", message="Scene boundary input contains a scene with non-positive duration.")
        scene_windows.append(
            SceneWindow(
                id=str(raw_scene.get("id") or f"scene-{index:04d}"),
                start_s=start_s,
                end_s=end_s,
                source=str(raw_scene.get("source") or "scene"),
            )
        )
    return scene_windows


def _load_audio_energy_windows(task_id: str, record) -> list[AudioEnergyWindow]:
    task_dirs = ensure_task_dirs(task_id)
    preferred_paths = [task_dirs["work"] / "audio-energy.json"]
    for preferred in preferred_paths:
        if preferred.exists():
            return _parse_audio_energy_windows(preferred)

    for artifact in reversed(record.artifacts):
        if artifact.kind == "audio_energy_json":
            candidate = Path(artifact.path)
            if candidate.exists():
                return _parse_audio_energy_windows(candidate)
    return []


def _parse_audio_energy_windows(path: Path) -> list[AudioEnergyWindow]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_windows = payload.get("windows") if isinstance(payload, dict) else payload
    if not isinstance(raw_windows, list):
        return []

    windows: list[AudioEnergyWindow] = []
    for raw_window in raw_windows:
        if not isinstance(raw_window, dict):
            continue
        try:
            windows.append(
                AudioEnergyWindow(
                    start_s=float(raw_window["start_s"]),
                    end_s=float(raw_window["end_s"]),
                    energy_delta=float(raw_window.get("energy_delta") or 0.0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return windows


def _load_segments_from_transcript(transcript_path: Path) -> list[SubtitleSegment]:
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise HighlightFailure(code="missing_input", message="Subtitle transcript JSON does not contain any segments to score.")

    segments: list[SubtitleSegment] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict):
            raise HighlightFailure(code="missing_input", message="Subtitle transcript JSON contains an invalid segment payload.")
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
                if isinstance(word, dict)
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


def _write_candidate_artifact(
    output_path: Path,
    *,
    transcript_path: Path,
    scene_path: Path | None,
    elapsed_seconds: float,
    candidates: list[dict[str, Any]],
    no_candidates: str | None,
) -> Path:
    payload = {
        "elapsed_seconds": elapsed_seconds,
        "transcript_path": str(transcript_path),
        "scene_path": str(scene_path) if scene_path is not None else None,
        "candidate_count": len(candidates),
        "no_candidates": no_candidates,
        "candidates": candidates,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def _write_scene_artifact(
    output_path: Path,
    *,
    source: str,
    source_video_reference: str | None,
    scene_windows: list[SceneWindow],
    provider_metadata: dict[str, object],
    fallback_reason: str | None,
) -> Path:
    payload = {
        "source": source,
        "source_video_path": source_video_reference,
        "provider_metadata": provider_metadata,
        "fallback_reason": fallback_reason,
        "scene_count": len(scene_windows),
        "scenes": [
            {
                "id": scene.id,
                "start_s": round(scene.start_s, 3),
                "end_s": round(scene.end_s, 3),
                "source": scene.source,
            }
            for scene in scene_windows
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def _classify_highlight_exception(exc: Exception) -> HighlightFailure:
    if isinstance(exc, HighlightFailure):
        return exc
    message = str(exc).strip() or exc.__class__.__name__
    return HighlightFailure(code="highlight_failed", message=f"Highlight analysis failed: {message}")
