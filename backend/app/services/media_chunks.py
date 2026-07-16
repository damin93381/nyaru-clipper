from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final


MEDIA_CHUNK_MANIFEST_FILENAME: Final = "media-chunks.json"
MEDIA_CHUNK_SCHEMA_VERSION: Final = 1
DEFAULT_MEDIA_CHUNK_SECONDS: Final = 300.0
_AUDIO_DIRECTORY: Final = "asr-audio-chunks"


class MediaChunkFailure(RuntimeError):
    """Raised when a media chunk manifest cannot be trusted."""

    code: Final[str] = "invalid_chunk_manifest"

    def __init__(self, detail: str) -> None:
        super().__init__(f"{self.code}: {detail}")


@dataclass(frozen=True, slots=True)
class MediaChunk:
    index: int
    start_seconds: float
    end_seconds: float
    audio_path: Path

    @property
    def id(self) -> str:
        """Return the stable identifier used by durable chunk artifacts."""
        return f"chunk-{self.index:04d}"


@dataclass(frozen=True, slots=True)
class MediaChunkManifest:
    source_duration_seconds: float
    chunk_seconds: float
    chunks: tuple[MediaChunk, ...]


def media_chunk_manifest_path(work_dir: Path) -> Path:
    """Return the canonical task-local manifest location."""
    return work_dir / MEDIA_CHUNK_MANIFEST_FILENAME


def build_media_chunk_manifest(
    source_duration_seconds: float,
    *,
    work_dir: Path,
    chunk_seconds: float = DEFAULT_MEDIA_CHUNK_SECONDS,
) -> MediaChunkManifest:
    """Build exact, contiguous source-time WAV chunk boundaries."""
    _validate_duration(source_duration_seconds, field_name="source_duration_seconds", allow_zero=True)
    _validate_duration(chunk_seconds, field_name="chunk_seconds", allow_zero=False)

    chunks: list[MediaChunk] = []
    start_seconds = 0.0
    index = 0
    while start_seconds < source_duration_seconds:
        end_seconds = min(start_seconds + chunk_seconds, source_duration_seconds)
        chunks.append(
            MediaChunk(
                index=index,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                audio_path=work_dir / _AUDIO_DIRECTORY / f"chunk-{index:04d}.wav",
            )
        )
        start_seconds = end_seconds
        index += 1

    manifest = MediaChunkManifest(
        source_duration_seconds=source_duration_seconds,
        chunk_seconds=chunk_seconds,
        chunks=tuple(chunks),
    )
    validate_media_chunk_manifest(manifest, work_dir=work_dir)
    return manifest


def load_media_chunk_manifest(
    manifest_path: Path,
    *,
    source_duration_seconds: float | None = None,
    chunk_seconds: float | None = None,
) -> MediaChunkManifest:
    """Load and validate a versioned manifest stored below a task work directory."""
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MediaChunkFailure("manifest is unreadable") from exc

    if not isinstance(payload, dict):
        raise MediaChunkFailure("manifest must be an object")

    manifest = _parse_manifest(payload, work_dir=manifest_path.parent)
    if source_duration_seconds is not None and manifest.source_duration_seconds != source_duration_seconds:
        raise MediaChunkFailure("manifest source duration is stale")
    if chunk_seconds is not None and manifest.chunk_seconds != chunk_seconds:
        raise MediaChunkFailure("manifest chunk duration is stale")
    return manifest


def write_media_chunk_manifest_atomically(manifest_path: Path, manifest: MediaChunkManifest) -> None:
    """Validate and atomically replace the durable task-local manifest."""
    work_dir = manifest_path.parent
    validate_media_chunk_manifest(manifest, work_dir=work_dir)
    payload = _serialize_manifest(manifest, work_dir=work_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=manifest_path.parent,
            prefix=f".{manifest_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(payload, temporary_file, ensure_ascii=False, indent=2, sort_keys=True)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.replace(manifest_path)
    except OSError as exc:
        raise MediaChunkFailure("manifest could not be written atomically") from exc


def validate_media_chunk_manifest(manifest: MediaChunkManifest, *, work_dir: Path) -> None:
    """Ensure a manifest is current, contiguous, and confined to task work storage."""
    _validate_duration(manifest.source_duration_seconds, field_name="source_duration_seconds", allow_zero=True)
    _validate_duration(manifest.chunk_seconds, field_name="chunk_seconds", allow_zero=False)

    if manifest.source_duration_seconds == 0.0 and manifest.chunks:
        raise MediaChunkFailure("zero-duration media must not contain chunks")

    expected_start = 0.0
    seen_indices: set[int] = set()
    seen_ids: set[str] = set()
    for position, chunk in enumerate(manifest.chunks):
        if chunk.index != position or chunk.index in seen_indices or chunk.id in seen_ids:
            raise MediaChunkFailure("chunk indices or IDs are duplicate or non-contiguous")
        if chunk.start_seconds != expected_start or chunk.end_seconds <= chunk.start_seconds:
            raise MediaChunkFailure("chunk ranges are not contiguous")
        if chunk.end_seconds > manifest.source_duration_seconds:
            raise MediaChunkFailure("chunk range exceeds source duration")
        if position < len(manifest.chunks) - 1 and chunk.end_seconds - chunk.start_seconds != manifest.chunk_seconds:
            raise MediaChunkFailure("non-final chunks must match the configured chunk duration")
        resolved_audio_path = validate_media_chunk_path(chunk.audio_path, work_dir=work_dir)
        expected_audio_path = (work_dir / _AUDIO_DIRECTORY / f"{chunk.id}.wav").resolve()
        if resolved_audio_path != expected_audio_path:
            raise MediaChunkFailure("chunk audio path does not match its stable ID")
        expected_start = chunk.end_seconds
        seen_indices.add(chunk.index)
        seen_ids.add(chunk.id)

    if expected_start != manifest.source_duration_seconds:
        raise MediaChunkFailure("chunk ranges do not cover the source duration")


def validate_media_chunk_path(audio_path: Path, *, work_dir: Path) -> Path:
    """Resolve a chunk WAV path only when it remains below the task work directory."""
    resolved_work_dir = work_dir.resolve()
    resolved_audio_path = audio_path.resolve()
    try:
        relative_path = resolved_audio_path.relative_to(resolved_work_dir)
    except ValueError as exc:
        raise MediaChunkFailure("chunk audio path escapes work directory") from exc
    if relative_path.parent != Path(_AUDIO_DIRECTORY) or relative_path.suffix != ".wav":
        raise MediaChunkFailure("chunk audio path is not a canonical work WAV path")
    return resolved_audio_path


def _parse_manifest(payload: dict[object, object], *, work_dir: Path) -> MediaChunkManifest:
    if payload.get("schema_version") != MEDIA_CHUNK_SCHEMA_VERSION:
        raise MediaChunkFailure("manifest schema version is unsupported or stale")
    source_duration_seconds = _read_number(payload, "source_duration_seconds", allow_zero=True)
    chunk_seconds = _read_number(payload, "chunk_seconds", allow_zero=False)
    raw_chunks = payload.get("chunks")
    if not isinstance(raw_chunks, list):
        raise MediaChunkFailure("manifest chunks must be a list")

    chunks: list[MediaChunk] = []
    for raw_chunk in raw_chunks:
        if not isinstance(raw_chunk, dict):
            raise MediaChunkFailure("chunk must be an object")
        index = raw_chunk.get("index")
        chunk_id = raw_chunk.get("id")
        audio_path = raw_chunk.get("audio_path")
        if isinstance(index, bool) or not isinstance(index, int):
            raise MediaChunkFailure("chunk index is invalid")
        if chunk_id != f"chunk-{index:04d}":
            raise MediaChunkFailure("chunk ID is invalid")
        if not isinstance(audio_path, str) or Path(audio_path).is_absolute():
            raise MediaChunkFailure("chunk audio path is invalid")
        chunks.append(
            MediaChunk(
                index=index,
                start_seconds=_read_number(raw_chunk, "start_seconds", allow_zero=True),
                end_seconds=_read_number(raw_chunk, "end_seconds", allow_zero=True),
                audio_path=work_dir / audio_path,
            )
        )

    manifest = MediaChunkManifest(source_duration_seconds, chunk_seconds, tuple(chunks))
    validate_media_chunk_manifest(manifest, work_dir=work_dir)
    return manifest


def _serialize_manifest(manifest: MediaChunkManifest, *, work_dir: Path) -> dict[str, object]:
    return {
        "schema_version": MEDIA_CHUNK_SCHEMA_VERSION,
        "source_duration_seconds": manifest.source_duration_seconds,
        "chunk_seconds": manifest.chunk_seconds,
        "chunks": [
            {
                "id": chunk.id,
                "index": chunk.index,
                "start_seconds": chunk.start_seconds,
                "end_seconds": chunk.end_seconds,
                "audio_path": str(validate_media_chunk_path(chunk.audio_path, work_dir=work_dir).relative_to(work_dir.resolve())),
            }
            for chunk in manifest.chunks
        ],
    }


def _read_number(payload: dict[object, object], field_name: str, *, allow_zero: bool) -> float:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MediaChunkFailure(f"{field_name} must be a number")
    numeric_value = float(value)
    _validate_duration(numeric_value, field_name=field_name, allow_zero=allow_zero)
    return numeric_value


def _validate_duration(value: float, *, field_name: str, allow_zero: bool) -> None:
    if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        raise MediaChunkFailure(f"{field_name} must be a finite positive duration")
