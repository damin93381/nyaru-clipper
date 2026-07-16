from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SubtitleWord:
    text: str
    start_seconds: float
    end_seconds: float
    confidence: float | None = None


@dataclass(slots=True)
class SubtitleSegment:
    id: str
    start_seconds: float
    end_seconds: float
    text: str
    words: list[SubtitleWord] | None = None


def _format_srt_timestamp(total_seconds: float) -> str:
    milliseconds = max(0, round(total_seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_srt(segments: list[SubtitleSegment]) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_format_srt_timestamp(segment.start_seconds)} --> {_format_srt_timestamp(segment.end_seconds)}",
                    segment.text,
                ]
            )
        )
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def _pair_segments_with_translations(
    segments: list[SubtitleSegment], translated_texts: list[str]
) -> list[tuple[SubtitleSegment, str]]:
    if len(segments) != len(translated_texts):
        raise ValueError("Translated text count must match the source segment count.")

    paired: list[tuple[SubtitleSegment, str]] = []
    for segment, translated_text in zip(segments, translated_texts, strict=True):
        paired.append((segment, str(translated_text).strip()))
    return paired


def render_bilingual_srt(segments: list[SubtitleSegment], translated_texts: list[str]) -> str:
    blocks: list[str] = []
    for index, (segment, translated_text) in enumerate(_pair_segments_with_translations(segments, translated_texts), start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_format_srt_timestamp(segment.start_seconds)} --> {_format_srt_timestamp(segment.end_seconds)}",
                    segment.text,
                    translated_text,
                ]
            )
        )
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def build_internal_subtitle_json(
    segments: list[SubtitleSegment],
    *,
    model_metadata: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    return {
        "elapsed_seconds": elapsed_seconds,
        "model_metadata": model_metadata,
        "segment_count": len(segments),
        "segments": [asdict(segment) for segment in segments],
    }


def build_bilingual_subtitle_json(
    segments: list[SubtitleSegment],
    translated_texts: list[str],
    *,
    model_metadata: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    bilingual_segments: list[dict[str, Any]] = []
    for segment, translated_text in _pair_segments_with_translations(segments, translated_texts):
        payload = asdict(segment)
        payload["translated_text"] = translated_text
        bilingual_segments.append(payload)

    return {
        "elapsed_seconds": elapsed_seconds,
        "model_metadata": model_metadata,
        "segment_count": len(segments),
        "segments": bilingual_segments,
    }


def write_subtitle_outputs(
    output_dir: Path,
    segments: list[SubtitleSegment],
    *,
    model_metadata: dict[str, Any],
    elapsed_seconds: float,
    transcript_filename: str = "asr-segments.json",
    srt_filename: str = "subtitles.zh.srt",
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / transcript_filename
    srt_path = output_dir / srt_filename

    transcript_payload = build_internal_subtitle_json(
        segments,
        model_metadata=model_metadata,
        elapsed_seconds=elapsed_seconds,
    )
    transcript_path.write_text(
        json.dumps(transcript_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    srt_path.write_text(render_srt(segments), encoding="utf-8")
    return transcript_path, srt_path


def write_bilingual_subtitle_outputs(
    output_dir: Path,
    segments: list[SubtitleSegment],
    translated_texts: list[str],
    *,
    model_metadata: dict[str, Any],
    elapsed_seconds: float,
    transcript_filename: str = "subtitles.zh-ja.json",
    srt_filename: str = "subtitles.zh-ja.srt",
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / transcript_filename
    srt_path = output_dir / srt_filename

    transcript_payload = build_bilingual_subtitle_json(
        segments,
        translated_texts,
        model_metadata=model_metadata,
        elapsed_seconds=elapsed_seconds,
    )
    transcript_path.write_text(
        json.dumps(transcript_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    srt_path.write_text(render_bilingual_srt(segments, translated_texts), encoding="utf-8")
    return transcript_path, srt_path


def write_bilingual_subtitle_outputs_atomically(
    output_dir: Path,
    segments: list[SubtitleSegment],
    translated_texts: list[str],
    *,
    model_metadata: dict[str, Any],
    elapsed_seconds: float,
    transcript_filename: str = "subtitles.zh-ja.json",
    srt_filename: str = "subtitles.zh-ja.srt",
) -> tuple[Path, Path]:
    """Publish a validated bilingual pair only after both complete replacement files exist."""
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / transcript_filename
    srt_path = output_dir / srt_filename
    transcript_payload = build_bilingual_subtitle_json(
        segments,
        translated_texts,
        model_metadata=model_metadata,
        elapsed_seconds=elapsed_seconds,
    )
    replacements: list[tuple[Path, str]] = [
        (transcript_path, json.dumps(transcript_payload, ensure_ascii=False, indent=2, sort_keys=True)),
        (srt_path, render_bilingual_srt(segments, translated_texts)),
    ]
    temporary_paths: list[Path] = []
    try:
        for destination, content in replacements:
            descriptor, temporary_name = tempfile.mkstemp(dir=output_dir, prefix=f".{destination.name}.")
            temporary_path = Path(temporary_name)
            temporary_paths.append(temporary_path)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                if destination.suffix == ".json":
                    handle.write("\n")
        for destination, _ in replacements:
            temporary_paths.pop(0).replace(destination)
    except OSError:
        for destination, _ in replacements:
            destination.unlink(missing_ok=True)
        raise
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)
    return transcript_path, srt_path
