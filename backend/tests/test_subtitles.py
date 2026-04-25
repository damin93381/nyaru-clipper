from __future__ import annotations

from app.services.subtitles import SubtitleSegment, SubtitleWord, build_internal_subtitle_json, render_srt


def test_generate_srt_from_segments() -> None:
    segments = [
        SubtitleSegment(
            id="seg-0001",
            start_seconds=0.0,
            end_seconds=1.25,
            text="你好",
            words=[SubtitleWord(text="你", start_seconds=0.0, end_seconds=0.5)],
        ),
        SubtitleSegment(
            id="seg-0002",
            start_seconds=1.25,
            end_seconds=3.5,
            text="今天也要加油。",
            words=None,
        ),
    ]

    srt_text = render_srt(segments)

    assert srt_text == (
        "1\n"
        "00:00:00,000 --> 00:00:01,250\n"
        "你好\n\n"
        "2\n"
        "00:00:01,250 --> 00:00:03,500\n"
        "今天也要加油。\n"
    )


def test_build_internal_json_preserves_ids_word_timings_and_metadata() -> None:
    segments = [
        SubtitleSegment(
            id="seg-0001",
            start_seconds=0.0,
            end_seconds=2.0,
            text="你好啊",
            words=[
                SubtitleWord(text="你好", start_seconds=0.0, end_seconds=1.0, confidence=0.91),
                SubtitleWord(text="啊", start_seconds=1.0, end_seconds=2.0),
            ],
        )
    ]

    payload = build_internal_subtitle_json(
        segments,
        model_metadata={"provider": "whisperx", "model_name": "large-v3"},
        elapsed_seconds=3.25,
    )

    assert payload == {
        "elapsed_seconds": 3.25,
        "model_metadata": {"provider": "whisperx", "model_name": "large-v3"},
        "segment_count": 1,
        "segments": [
            {
                "id": "seg-0001",
                "start_seconds": 0.0,
                "end_seconds": 2.0,
                "text": "你好啊",
                "words": [
                    {
                        "text": "你好",
                        "start_seconds": 0.0,
                        "end_seconds": 1.0,
                        "confidence": 0.91,
                    },
                    {
                        "text": "啊",
                        "start_seconds": 1.0,
                        "end_seconds": 2.0,
                        "confidence": None,
                    },
                ],
            }
        ],
    }
