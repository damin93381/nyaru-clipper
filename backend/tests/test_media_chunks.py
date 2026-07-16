from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_build_media_chunk_manifest_uses_exact_source_boundaries(tmp_path: Path) -> None:
    from app.services.media_chunks import build_media_chunk_manifest

    work_dir = tmp_path / "work"

    assert build_media_chunk_manifest(0, work_dir=work_dir).chunks == ()

    exact_chunk = build_media_chunk_manifest(300, work_dir=work_dir)
    assert [(chunk.index, chunk.start_seconds, chunk.end_seconds) for chunk in exact_chunk.chunks] == [
        (0, 0.0, 300.0)
    ]

    remainder = build_media_chunk_manifest(300.001, work_dir=work_dir)
    assert [(chunk.index, chunk.start_seconds, chunk.end_seconds) for chunk in remainder.chunks] == [
        (0, 0.0, 300.0),
        (1, 300.0, 300.001),
    ]

    two_chunks = build_media_chunk_manifest(600, work_dir=work_dir)
    assert [(chunk.index, chunk.start_seconds, chunk.end_seconds) for chunk in two_chunks.chunks] == [
        (0, 0.0, 300.0),
        (1, 300.0, 600.0),
    ]

    final_remainder = build_media_chunk_manifest(601.25, work_dir=work_dir)
    assert [(chunk.index, chunk.start_seconds, chunk.end_seconds) for chunk in final_remainder.chunks] == [
        (0, 0.0, 300.0),
        (1, 300.0, 600.0),
        (2, 600.0, 601.25),
    ]
    assert [chunk.audio_path.name for chunk in final_remainder.chunks] == [
        "chunk-0000.wav",
        "chunk-0001.wav",
        "chunk-0002.wav",
    ]
    assert all(chunk.audio_path.is_relative_to(work_dir) for chunk in final_remainder.chunks)


def test_media_chunk_manifest_round_trips_atomically(tmp_path: Path) -> None:
    from app.services.media_chunks import (
        build_media_chunk_manifest,
        load_media_chunk_manifest,
        write_media_chunk_manifest_atomically,
    )

    work_dir = tmp_path / "work"
    manifest_path = work_dir / "media-chunks.json"
    manifest = build_media_chunk_manifest(601.25, work_dir=work_dir)

    write_media_chunk_manifest_atomically(manifest_path, manifest)

    assert load_media_chunk_manifest(manifest_path) == manifest
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["chunks"][0]["id"] == "chunk-0000"
    assert payload["chunks"][0]["audio_path"] == "asr-audio-chunks/chunk-0000.wav"


@pytest.mark.parametrize(
    ("payload", "work_dir"),
    [
        ({}, "work"),
        (
            {
                "schema_version": 1,
                "source_duration_seconds": 300,
                "chunk_seconds": 300,
                "chunks": [
                    {
                        "id": "chunk-0000",
                        "index": 0,
                        "start_seconds": 0,
                        "end_seconds": 300,
                    }
                ],
            },
            "work",
        ),
        (
            {
                "schema_version": 0,
                "source_duration_seconds": 0,
                "chunk_seconds": 300,
                "chunks": [],
            },
            "work",
        ),
        (
            {
                "schema_version": 1,
                "source_duration_seconds": 300,
                "chunk_seconds": 300,
                "chunks": [
                    {
                        "id": "chunk-0000",
                        "index": 0,
                        "start_seconds": 0,
                        "end_seconds": 300,
                        "audio_path": "../escape.wav",
                    }
                ],
            },
            "work",
        ),
        (
            {
                "schema_version": 1,
                "source_duration_seconds": 600,
                "chunk_seconds": 300,
                "chunks": [
                    {
                        "id": "chunk-0000",
                        "index": 0,
                        "start_seconds": 0,
                        "end_seconds": 300,
                        "audio_path": "asr-audio-chunks/chunk-0000.wav",
                    },
                    {
                        "id": "chunk-0000",
                        "index": 1,
                        "start_seconds": 300,
                        "end_seconds": 600,
                        "audio_path": "asr-audio-chunks/chunk-0001.wav",
                    },
                ],
            },
            "work",
        ),
        (
            {
                "schema_version": 1,
                "source_duration_seconds": 600,
                "chunk_seconds": 300,
                "chunks": [
                    {
                        "id": "chunk-0000",
                        "index": 0,
                        "start_seconds": 0,
                        "end_seconds": 300,
                        "audio_path": "asr-audio-chunks/chunk-0000.wav",
                    },
                    {
                        "id": "chunk-0001",
                        "index": 1,
                        "start_seconds": 300,
                        "end_seconds": 600,
                        "audio_path": "asr-audio-chunks/chunk-0000.wav",
                    },
                ],
            },
            "work",
        ),
        (
            {
                "schema_version": 1,
                "source_duration_seconds": 300,
                "chunk_seconds": 300,
                "chunks": [
                    {
                        "id": "chunk-0000",
                        "index": 0,
                        "start_seconds": 0,
                        "end_seconds": 299,
                        "audio_path": "asr-audio-chunks/chunk-0000.wav",
                    }
                ],
            },
            "work",
        ),
    ],
)
def test_load_media_chunk_manifest_rejects_invalid_payload(
    tmp_path: Path, payload: dict[str, object], work_dir: str
) -> None:
    from app.services.media_chunks import MediaChunkFailure, load_media_chunk_manifest

    manifest_path = tmp_path / work_dir / "media-chunks.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MediaChunkFailure, match="invalid_chunk_manifest") as failure:
        load_media_chunk_manifest(manifest_path)

    assert failure.value.code == "invalid_chunk_manifest"
