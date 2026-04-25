from __future__ import annotations

import json

from app.services.subtitles import (
    SubtitleSegment,
    SubtitleWord,
    build_bilingual_subtitle_json,
    render_bilingual_srt,
    write_bilingual_subtitle_outputs,
)


def test_emit_bilingual_srt_preserves_segment_boundaries_and_two_lines_per_cue(tmp_path) -> None:
    segments = [
        SubtitleSegment(
            id="seg-0001",
            start_seconds=0.0,
            end_seconds=1.5,
            text="早上好",
            words=[SubtitleWord(text="早上好", start_seconds=0.0, end_seconds=1.5)],
        ),
        SubtitleSegment(
            id="seg-0002",
            start_seconds=1.5,
            end_seconds=3.75,
            text="今天也要加油。",
            words=None,
        ),
    ]
    translated_texts = ["おはようございます", "今日も頑張ろう。"]

    srt_text = render_bilingual_srt(segments, translated_texts)

    assert srt_text == (
        "1\n"
        "00:00:00,000 --> 00:00:01,500\n"
        "早上好\n"
        "おはようございます\n\n"
        "2\n"
        "00:00:01,500 --> 00:00:03,750\n"
        "今天也要加油。\n"
        "今日も頑張ろう。\n"
    )

    transcript_path, subtitle_path = write_bilingual_subtitle_outputs(
        tmp_path,
        segments,
        translated_texts,
        model_metadata={"provider": "hf", "model_name": "fake-nllb"},
        elapsed_seconds=2.5,
    )

    assert subtitle_path.name == "subtitles.zh-ja.srt"
    assert subtitle_path.read_text(encoding="utf-8") == srt_text

    transcript_payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert transcript_payload["segment_count"] == 2
    assert transcript_payload["segments"][0]["id"] == "seg-0001"
    assert transcript_payload["segments"][0]["start_seconds"] == 0.0
    assert transcript_payload["segments"][0]["end_seconds"] == 1.5
    assert transcript_payload["segments"][0]["text"] == "早上好"
    assert transcript_payload["segments"][0]["translated_text"] == "おはようございます"


def test_build_bilingual_json_preserves_original_words_and_metadata() -> None:
    payload = build_bilingual_subtitle_json(
        [
            SubtitleSegment(
                id="seg-0003",
                start_seconds=4.0,
                end_seconds=5.0,
                text="谢谢大家",
                words=[
                    SubtitleWord(text="谢谢", start_seconds=4.0, end_seconds=4.5, confidence=0.94),
                    SubtitleWord(text="大家", start_seconds=4.5, end_seconds=5.0, confidence=0.9),
                ],
            )
        ],
        ["皆さんありがとうございます"],
        model_metadata={"provider": "hf", "model_name": "facebook/nllb-200-distilled-600M"},
        elapsed_seconds=1.75,
    )

    assert payload == {
        "elapsed_seconds": 1.75,
        "model_metadata": {"provider": "hf", "model_name": "facebook/nllb-200-distilled-600M"},
        "segment_count": 1,
        "segments": [
            {
                "id": "seg-0003",
                "start_seconds": 4.0,
                "end_seconds": 5.0,
                "text": "谢谢大家",
                "translated_text": "皆さんありがとうございます",
                "words": [
                    {
                        "text": "谢谢",
                        "start_seconds": 4.0,
                        "end_seconds": 4.5,
                        "confidence": 0.94,
                    },
                    {
                        "text": "大家",
                        "start_seconds": 4.5,
                        "end_seconds": 5.0,
                        "confidence": 0.9,
                    },
                ],
            }
        ],
    }
