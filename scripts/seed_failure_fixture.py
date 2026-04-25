#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_TASK_ID = "task-flow-failed123"
DEFAULT_PUBLIC_PREFIX = f"/fixtures/{DEFAULT_TASK_ID}"


def build_stages() -> list[dict[str, object]]:
    return [
        {"name": "ingest", "status": "success", "summary": "Downloaded source video via bbdown", "attempts": 1},
        {"name": "media_prep", "status": "success", "summary": "Prepared ffprobe metadata and ASR wav", "attempts": 1},
        {"name": "asr", "status": "success", "summary": "Generated aligned transcript and Chinese subtitles", "attempts": 1},
        {"name": "translation", "status": "failed", "summary": "translation_failed", "attempts": 2},
        {"name": "highlight", "status": "pending", "summary": None, "attempts": 0},
        {"name": "export", "status": "pending", "summary": None, "attempts": 0},
        {"name": "report", "status": "pending", "summary": None, "attempts": 0},
    ]


def build_subtitle_payload() -> dict[str, object]:
    return {
        "segment_count": 2,
        "model_metadata": {"provider": "hf", "model_name": "fixture-translator"},
        "segments": [
            {
                "id": "seg-fail-0001",
                "start_seconds": 12.0,
                "end_seconds": 15.2,
                "text": "翻译失败前的保留字幕。",
                "translated_text": "翻訳失敗前の保持字幕。",
            },
            {
                "id": "seg-fail-0002",
                "start_seconds": 15.2,
                "end_seconds": 18.5,
                "text": "可以从这里重新开始。",
                "translated_text": "ここから再開できます。",
            },
        ],
    }


def build_srt() -> str:
    return "\n".join(
        [
            "1",
            "00:00:12,000 --> 00:00:15,200",
            "翻译失败前的保留字幕。",
            "翻訳失敗前の保持字幕。",
            "",
            "2",
            "00:00:15,200 --> 00:00:18,500",
            "可以从这里重新开始。",
            "ここから再開できます。",
            "",
        ]
    )


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Write deterministic failed-translation browser fixtures.")
    parser.add_argument("output_dir", type=Path, help="Directory where the fixture files will be written")
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID, help="Task identifier embedded in the evidence payloads")
    parser.add_argument(
        "--public-prefix",
        default=DEFAULT_PUBLIC_PREFIX,
        help="Browser-visible prefix used for artifact path values inside task-artifacts.json",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    stages = build_stages()
    subtitle_payload = build_subtitle_payload()
    public_prefix = args.public_prefix.rstrip("/")
    task_id = args.task_id
    source_url = f"https://www.bilibili.com/video/{task_id}"

    write_json(output_dir / "task-detail.json", {
        "task_id": task_id,
        "source_url": source_url,
        "normalized_source_url": source_url,
        "source_video_id": task_id,
        "status": "failed",
        "stages": stages,
    })
    write_json(output_dir / "task-stages.json", stages)
    write_json(
        output_dir / "task-logs.json",
        [
            {
                "stage_name": stage["name"],
                "status": stage["status"],
                "summary": "translation_failed" if stage["name"] == "translation" else stage["summary"],
                "log_path": f"/data/tasks/{task_id}/logs/{stage['name']}.log",
            }
            for stage in stages
        ],
    )
    write_json(
        output_dir / "task-artifacts.json",
        [
            {
                "id": 1,
                "task_id": task_id,
                "stage_name": "translation",
                "kind": "bilingual_transcript_json",
                "path": f"{public_prefix}/subtitles.zh-ja.json",
                "metadata_json": json.dumps(
                    {
                        "segment_count": subtitle_payload["segment_count"],
                        "model_metadata": subtitle_payload["model_metadata"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
            {
                "id": 2,
                "task_id": task_id,
                "stage_name": "translation",
                "kind": "bilingual_subtitle_srt",
                "path": f"{public_prefix}/subtitles.zh-ja.srt",
                "metadata_json": "{}",
            },
        ],
    )
    write_json(output_dir / "subtitles.zh-ja.json", subtitle_payload)
    (output_dir / "subtitles.zh-ja.srt").write_text(build_srt(), encoding="utf-8")

    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
