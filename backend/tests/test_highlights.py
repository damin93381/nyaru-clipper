from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import select


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


@pytest.fixture()
def backend_env(tmp_path, monkeypatch) -> dict[str, Path | str]:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{db_path}")
    _reset_runtime_state()
    return {"data_dir": data_dir, "db_path": db_path}


def _create_task(source_url: str) -> str:
    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, source_url)
        return payload["task_id"]


def _prepare_translation_fixture(data_dir: Path, task_id: str, *, excited: bool) -> Path:
    transcript_path = data_dir / "tasks" / task_id / "work" / "subtitles.zh-ja.json"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)

    if excited:
        segments = [
            {
                "id": "seg-0001",
                "start_seconds": 0.0,
                "end_seconds": 6.0,
                "text": "今天继续聊天。",
                "translated_text": "今日は雑談を続けます。",
                "words": None,
            },
            {
                "id": "seg-0002",
                "start_seconds": 18.0,
                "end_seconds": 24.0,
                "text": "不会吧！！这也太强了！！！",
                "translated_text": "うそでしょ！！強すぎる！！！",
                "words": None,
            },
            {
                "id": "seg-0003",
                "start_seconds": 24.0,
                "end_seconds": 31.0,
                "text": "哈哈哈哈哈哈，真的做到了！",
                "translated_text": "はははは、本当にできた！",
                "words": None,
            },
            {
                "id": "seg-0004",
                "start_seconds": 31.0,
                "end_seconds": 39.0,
                "text": "太神了太神了，啊啊啊！！！",
                "translated_text": "すごすぎる、あああ！！！",
                "words": None,
            },
            {
                "id": "seg-0005",
                "start_seconds": 48.0,
                "end_seconds": 54.0,
                "text": "后面继续看看吧。",
                "translated_text": "このあとも見ていきましょう。",
                "words": None,
            },
        ]
    else:
        segments = [
            {
                "id": "seg-0001",
                "start_seconds": 2.0,
                "end_seconds": 6.0,
                "text": "今天继续讲设定。",
                "translated_text": "今日は設定を続けて話します。",
                "words": None,
            },
            {
                "id": "seg-0002",
                "start_seconds": 24.0,
                "end_seconds": 28.0,
                "text": "然后慢慢看下一个部分。",
                "translated_text": "それから次の部分をゆっくり見ます。",
                "words": None,
            },
            {
                "id": "seg-0003",
                "start_seconds": 52.0,
                "end_seconds": 56.0,
                "text": "最后整理一下。",
                "translated_text": "最後に整理します。",
                "words": None,
            },
        ]

    transcript_path.write_text(
        json.dumps(
            {
                "elapsed_seconds": 3.2,
                "model_metadata": {"provider": "hf", "model_name": "fixture-translator"},
                "segment_count": len(segments),
                "segments": segments,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return transcript_path


def _prepare_source_video_fixture(data_dir: Path, task_id: str) -> Path:
    source_video_path = data_dir / "tasks" / task_id / "raw" / "source.mp4"
    source_video_path.parent.mkdir(parents=True, exist_ok=True)
    source_video_path.write_bytes(b"fixture-video")
    return source_video_path


def _prepare_audio_energy_fixture(data_dir: Path, task_id: str) -> Path:
    energy_path = data_dir / "tasks" / task_id / "work" / "audio-energy.json"
    energy_path.parent.mkdir(parents=True, exist_ok=True)
    energy_path.write_text(
        json.dumps(
            {
                "source": "fixture-audio-energy",
                "windows": [
                    {"start_s": 0.0, "end_s": 18.0, "energy_delta": 0.08},
                    {"start_s": 18.0, "end_s": 42.0, "energy_delta": 0.82},
                    {"start_s": 42.0, "end_s": 72.0, "energy_delta": 0.12},
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return energy_path


class StubSceneDetectionProvider:
    def __init__(self, *, scenes, error: Exception | None = None, metadata: dict[str, object] | None = None):
        self._scenes = list(scenes)
        self._error = error
        self.metadata = metadata or {"provider": "stub-scenedetect", "detector": "content"}
        self.calls: list[Path] = []

    def detect_scenes(self, video_path: Path):
        self.calls.append(video_path)
        if self._error is not None:
            raise self._error
        return list(self._scenes)


def test_generates_ranked_candidates_via_scene_detection_provider(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1hs411c7mW")
    data_dir = Path(backend_env["data_dir"])
    _prepare_translation_fixture(data_dir, task_id, excited=True)
    source_video_path = _prepare_source_video_fixture(data_dir, task_id)
    _prepare_audio_energy_fixture(data_dir, task_id)

    perf_values = iter([20.0, 21.75])
    monkeypatch.setattr("app.services.highlights.time.perf_counter", lambda: next(perf_values))

    from app.db import session_scope
    from app.models import Artifact, ClipCandidate, TaskStage
    from app.services.highlight_scoring import SceneWindow
    from app.services.highlights import analyze_task_highlights

    provider = StubSceneDetectionProvider(
        scenes=[
            SceneWindow(id="scene-0001", start_s=0.0, end_s=18.0, source="pyscenedetect"),
            SceneWindow(id="scene-0002", start_s=18.0, end_s=42.0, source="pyscenedetect"),
            SceneWindow(id="scene-0003", start_s=42.0, end_s=72.0, source="pyscenedetect"),
        ],
        metadata={"provider": "stub-scenedetect", "detector": "content", "threshold": 27.0},
    )

    with session_scope() as session:
        result = analyze_task_highlights(session, task_id, scene_detection_provider=provider)

    assert result.elapsed_seconds == 1.75
    assert result.no_candidates is None
    assert len(result.candidates) >= 1
    assert provider.calls == [source_video_path]
    assert result.scene_path is not None
    assert result.scene_path.name == "scene-boundaries.json"
    top_candidate = result.candidates[0]
    assert set(["start_s", "end_s", "score", "reasons", "status"]).issubset(top_candidate.keys())
    assert top_candidate["status"] == "candidate"
    assert top_candidate["start_s"] == 18.0
    assert top_candidate["end_s"] == 42.0
    assert "laughter_phrase" in top_candidate["reasons"]
    assert "emphasis_punctuation" in top_candidate["reasons"]
    assert result.artifact_path.exists()

    persisted_payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert persisted_payload["candidate_count"] == len(result.candidates)
    assert persisted_payload["no_candidates"] is None
    assert persisted_payload["scene_path"] == str(result.scene_path)
    assert persisted_payload["candidates"][0]["score_breakdown"]["total"] == top_candidate["score"]
    assert persisted_payload["candidates"][0]["source_signals"]["audio_energy_delta"] == 0.82
    assert persisted_payload["candidates"][0]["default_range"] == {"start_s": 16.0, "end_s": 44.0}
    scene_payload = json.loads(result.scene_path.read_text(encoding="utf-8"))
    assert scene_payload["source"] == "pyscenedetect"
    assert scene_payload["provider_metadata"]["provider"] == "stub-scenedetect"
    assert scene_payload["scene_count"] == 3

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "highlight")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "highlight")
        ).all()
        clip_candidates = session.exec(select(ClipCandidate).where(ClipCandidate.task_id == task_id)).all()
        stage_status = stage.status
        stage_summary = stage.summary
        artifact_kinds = {artifact.kind for artifact in artifacts}
        artifact_metadata_by_kind = {artifact.kind: json.loads(artifact.metadata_json) for artifact in artifacts}
        clip_candidate_count = len(clip_candidates)
        clip_candidate_status = clip_candidates[0].status
        clip_candidate_id = clip_candidates[0].id
        clip_candidate_start = clip_candidates[0].start_seconds
        clip_candidate_end = clip_candidates[0].end_seconds

    assert stage_status == "success"
    assert stage_summary == "Ranked 1 highlight candidate windows"
    assert artifact_kinds == {"highlight_candidates_json", "scene_boundaries_json"}
    assert artifact_metadata_by_kind["scene_boundaries_json"]["provider_metadata"]["provider"] == "stub-scenedetect"
    assert artifact_metadata_by_kind["scene_boundaries_json"]["scene_count"] == 3
    assert persisted_payload["candidates"][0]["candidate_id"] == clip_candidate_id
    assert clip_candidate_count == 1
    assert clip_candidate_status == "candidate"
    assert clip_candidate_start == 18.0
    assert clip_candidate_end == 42.0


def test_no_candidate_is_success_not_failure_with_scene_detection_provider(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1is411c7mX")
    data_dir = Path(backend_env["data_dir"])
    _prepare_translation_fixture(data_dir, task_id, excited=False)
    source_video_path = _prepare_source_video_fixture(data_dir, task_id)

    perf_values = iter([30.0, 30.9])
    monkeypatch.setattr("app.services.highlights.time.perf_counter", lambda: next(perf_values))

    from app.db import session_scope
    from app.models import Artifact, ClipCandidate, TaskStage
    from app.services.highlight_scoring import SceneWindow
    from app.services.highlights import analyze_task_highlights

    provider = StubSceneDetectionProvider(
        scenes=[
            SceneWindow(id="scene-0001", start_s=0.0, end_s=18.0, source="pyscenedetect"),
            SceneWindow(id="scene-0002", start_s=18.0, end_s=42.0, source="pyscenedetect"),
            SceneWindow(id="scene-0003", start_s=42.0, end_s=72.0, source="pyscenedetect"),
        ],
    )

    with session_scope() as session:
        result = analyze_task_highlights(session, task_id, scene_detection_provider=provider)

    assert result.elapsed_seconds == 0.9
    assert result.candidates == []
    assert provider.calls == [source_video_path]
    assert result.scene_path is not None
    assert result.scene_path.name == "scene-boundaries.json"
    assert result.no_candidates == (
        "No highlight candidates cleared the minimum score threshold from the available scene and subtitle signals."
    )
    persisted_payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert persisted_payload["candidates"] == []
    assert persisted_payload["candidate_count"] == 0
    assert persisted_payload["no_candidates"] == result.no_candidates

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "highlight")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "highlight")
        ).all()
        clip_candidates = session.exec(select(ClipCandidate).where(ClipCandidate.task_id == task_id)).all()
        stage_status = stage.status
        stage_summary = stage.summary
        artifact_kinds = {artifact.kind for artifact in artifacts}
        clip_candidate_count = len(clip_candidates)

    assert stage_status == "success"
    assert stage_summary == result.no_candidates
    assert artifact_kinds == {"highlight_candidates_json", "scene_boundaries_json"}
    assert clip_candidate_count == 0


def test_scene_detection_fallback_derives_scene_like_windows(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1as411c7mZ")
    data_dir = Path(backend_env["data_dir"])
    _prepare_translation_fixture(data_dir, task_id, excited=True)
    source_video_path = _prepare_source_video_fixture(data_dir, task_id)
    _prepare_audio_energy_fixture(data_dir, task_id)

    perf_values = iter([40.0, 41.1])
    monkeypatch.setattr("app.services.highlights.time.perf_counter", lambda: next(perf_values))

    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.highlights import analyze_task_highlights

    provider = StubSceneDetectionProvider(scenes=[], error=ModuleNotFoundError("scenedetect"))

    with session_scope() as session:
        result = analyze_task_highlights(session, task_id, scene_detection_provider=provider)

    assert provider.calls == [source_video_path]
    assert result.scene_path is not None
    assert result.scene_path.name == "scene-like-boundaries.json"
    assert result.candidates
    fallback_payload = json.loads(result.scene_path.read_text(encoding="utf-8"))
    assert fallback_payload["source"] == "subtitle_gap_fallback"
    assert fallback_payload["fallback_reason"]
    assert fallback_payload["scene_count"] >= 1

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "highlight")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "highlight")
        ).all()
        stage_status = stage.status
        artifact_kinds = {artifact.kind for artifact in artifacts}

    assert stage_status == "success"
    assert artifact_kinds == {"highlight_candidates_json", "scene_like_boundaries_json"}
