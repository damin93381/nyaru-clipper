from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.subtitles import SubtitleSegment

LAUGHTER_TOKENS = ("哈哈", "hhh", "HHH", "233", "www", "ｗｗ", "草", "笑死")
EXCITEMENT_TOKENS = ("不会吧", "太强", "太神", "啊啊", "哇", "神了", "好厉害", "真的假的")
MIN_CANDIDATE_SCORE = 0.55


@dataclass(slots=True)
class SceneWindow:
    id: str
    start_s: float
    end_s: float
    source: str = "scene"


@dataclass(slots=True)
class AudioEnergyWindow:
    start_s: float
    end_s: float
    energy_delta: float


def derive_scene_like_windows(
    segments: list[SubtitleSegment],
    *,
    gap_threshold_s: float = 6.0,
    max_window_duration_s: float = 45.0,
) -> list[SceneWindow]:
    if not segments:
        return []

    windows: list[SceneWindow] = []
    current_start = segments[0].start_seconds
    current_end = segments[0].end_seconds
    index = 1

    for segment in segments[1:]:
        gap = segment.start_seconds - current_end
        if gap >= gap_threshold_s or (segment.end_seconds - current_start) > max_window_duration_s:
            windows.append(SceneWindow(id=f"derived-{index:04d}", start_s=current_start, end_s=current_end, source="subtitle_gap"))
            index += 1
            current_start = segment.start_seconds
        current_end = max(current_end, segment.end_seconds)

    windows.append(SceneWindow(id=f"derived-{index:04d}", start_s=current_start, end_s=current_end, source="subtitle_gap"))
    return windows


def score_candidate_windows(
    scene_windows: list[SceneWindow],
    subtitle_segments: list[SubtitleSegment],
    *,
    audio_energy_windows: list[AudioEnergyWindow] | None = None,
    media_end_s: float | None = None,
    min_score: float = MIN_CANDIDATE_SCORE,
) -> list[dict[str, Any]]:
    if not scene_windows:
        return []

    effective_media_end = media_end_s
    if effective_media_end is None and scene_windows:
        effective_media_end = max(window.end_s for window in scene_windows)
    if effective_media_end is None and subtitle_segments:
        effective_media_end = max(segment.end_seconds for segment in subtitle_segments)

    candidates: list[dict[str, Any]] = []
    for rank_index, scene in enumerate(scene_windows, start=1):
        window_segments = [
            segment
            for segment in subtitle_segments
            if segment.end_seconds > scene.start_s and segment.start_seconds < scene.end_s
        ]
        duration = max(scene.end_s - scene.start_s, 0.001)
        combined_text = " ".join(segment.text.strip() for segment in window_segments if segment.text.strip())
        char_count = len(re.sub(r"\s+", "", combined_text))
        subtitle_density = round(char_count / duration, 3)
        punctuation_hits = len(re.findall(r"[!！?？]", combined_text))
        laughter_hits = sum(combined_text.count(token) for token in LAUGHTER_TOKENS)
        excitement_hits = sum(combined_text.count(token) for token in EXCITEMENT_TOKENS)
        repeated_phrase_hits = sum(1 for token in (*LAUGHTER_TOKENS, *EXCITEMENT_TOKENS) if combined_text.count(token) >= 2)
        audio_energy_delta = _resolve_audio_energy_delta(scene, audio_energy_windows or [])

        score_breakdown = {
            "subtitle_density": round(0.35 * min(subtitle_density / 1.2, 1.0), 3),
            "emphasis_punctuation": round(0.18 * min(punctuation_hits / 4.0, 1.0), 3),
            "laughter_phrase": round(0.14 * min(laughter_hits / 2.0, 1.0), 3),
            "excitement_phrase": round(0.16 * min(excitement_hits / 2.0, 1.0), 3),
            "repeated_phrase": round(0.07 * min(repeated_phrase_hits / 2.0, 1.0), 3),
            "audio_energy_delta": round(0.15 * min(max(audio_energy_delta, 0.0) / 0.8, 1.0), 3),
            "duration_fit": _duration_fit_score(duration),
        }
        total_score = round(sum(score_breakdown.values()), 3)
        score_breakdown["total"] = total_score

        reasons = [
            code
            for code in (
                "subtitle_density",
                "emphasis_punctuation",
                "laughter_phrase",
                "excitement_phrase",
                "repeated_phrase",
                "audio_energy_delta",
            )
            if score_breakdown[code] > 0.0
        ]

        if total_score < min_score:
            continue

        default_range = {
            "start_s": round(max(0.0, scene.start_s - 2.0), 3),
            "end_s": round(min(effective_media_end or scene.end_s, scene.end_s + 2.0), 3),
        }
        candidates.append(
            {
                "rank": rank_index,
                "scene_id": scene.id,
                "scene_source": scene.source,
                "start_s": round(scene.start_s, 3),
                "end_s": round(scene.end_s, 3),
                "score": total_score,
                "reasons": reasons,
                "status": "candidate",
                "source_signals": {
                    "segment_count": len(window_segments),
                    "subtitle_char_count": char_count,
                    "subtitle_density": subtitle_density,
                    "punctuation_hits": punctuation_hits,
                    "laughter_hits": laughter_hits,
                    "excitement_hits": excitement_hits,
                    "repeated_phrase_hits": repeated_phrase_hits,
                    "audio_energy_delta": round(audio_energy_delta, 3),
                },
                "score_breakdown": score_breakdown,
                "default_range": default_range,
            }
        )

    return sorted(candidates, key=lambda candidate: (-candidate["score"], candidate["start_s"]))


def _duration_fit_score(duration: float) -> float:
    if 10.0 <= duration <= 55.0:
        return 0.05
    if duration < 5.0 or duration > 90.0:
        return -0.05
    return 0.0


def _resolve_audio_energy_delta(scene: SceneWindow, audio_energy_windows: list[AudioEnergyWindow]) -> float:
    best_match = 0.0
    for window in audio_energy_windows:
        overlap = min(scene.end_s, window.end_s) - max(scene.start_s, window.start_s)
        if overlap <= 0:
            continue
        if overlap >= min(scene.end_s - scene.start_s, window.end_s - window.start_s) * 0.5:
            best_match = max(best_match, window.energy_delta)
    return best_match
