from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import pytest
from sqlmodel import select


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def _create_task(source_url: str, *, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{data_dir.parent / 'task-state.sqlite3'}")
    _reset_runtime_state()

    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, source_url)
        return payload["task_id"]


def _write_wav(path: Path, *, duration_seconds: float) -> None:
    frame_count = round(duration_seconds * 16000)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * frame_count)


def _install_media_commands(monkeypatch: pytest.MonkeyPatch, commands: list[list[str]], *, duration: str) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(list(args))
        match args[0]:
            case "ffprobe":
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout=json.dumps({"format": {"duration": duration}, "streams": []}),
                    stderr="",
                )
            case "ffmpeg":
                output_path = Path(args[-1])
                _write_wav(output_path, duration_seconds=float(args[args.index("-t") + 1]))
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
            case unexpected:
                raise AssertionError(f"unexpected command: {unexpected}")

    monkeypatch.setattr("subprocess.run", fake_run)


def test_prepare_media_for_asr_creates_exact_wav_chunks_and_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task("https://www.bilibili.com/video/BV1mn411c7mP", data_dir=data_dir, monkeypatch=monkeypatch)
    video_path = data_dir / "tasks" / task_id / "raw" / "source.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video-bytes")
    commands: list[list[str]] = []
    _install_media_commands(monkeypatch, commands, duration="601.25")

    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.media_prep import prepare_media_for_asr

    with session_scope() as session:
        result = prepare_media_for_asr(session, task_id, video_path)

    assert [command[0] for command in commands] == ["ffprobe", "ffmpeg", "ffmpeg", "ffmpeg"]
    assert [(chunk.index, chunk.start_seconds, chunk.end_seconds) for chunk in result.chunk_manifest.chunks] == [
        (0, 0.0, 300.0),
        (1, 300.0, 600.0),
        (2, 600.0, 601.25),
    ]
    assert [command[command.index("-ss") + 1] for command in commands[1:]] == ["0.0", "300.0", "600.0"]
    assert [command[command.index("-t") + 1] for command in commands[1:]] == ["300.0", "300.0", "1.25"]
    assert all(chunk.audio_path.exists() for chunk in result.chunk_manifest.chunks)
    assert not (data_dir / "tasks" / task_id / "work" / "asr-input.wav").exists()

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "media_prep")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "media_prep")
        ).all()
        stage_status = stage.status
        artifact_kinds = {artifact.kind for artifact in artifacts}
        audio_chunk_artifact_count = len([artifact for artifact in artifacts if artifact.kind == "asr_audio_chunk"])

    assert stage_status == "success"
    assert artifact_kinds == {"media_probe", "media_chunk_manifest", "asr_audio_chunk"}
    assert audio_chunk_artifact_count == 3


def test_prepare_media_for_asr_reuses_valid_matching_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task("https://www.bilibili.com/video/BV1mn411c7mP", data_dir=data_dir, monkeypatch=monkeypatch)
    video_path = data_dir / "tasks" / task_id / "raw" / "source.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video-bytes")
    commands: list[list[str]] = []
    _install_media_commands(monkeypatch, commands, duration="601.25")

    from app.db import session_scope
    from app.services.media_prep import prepare_media_for_asr

    with session_scope() as session:
        first_result = prepare_media_for_asr(session, task_id, video_path)
    commands.clear()

    with session_scope() as session:
        second_result = prepare_media_for_asr(session, task_id, video_path)

    assert [command[0] for command in commands] == ["ffprobe"]
    assert second_result.chunk_manifest == first_result.chunk_manifest


def test_prepare_media_for_asr_reuses_artifact_rows_and_ready_events_for_matching_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task("https://www.bilibili.com/video/BV1mn411c7mP", data_dir=data_dir, monkeypatch=monkeypatch)
    video_path = data_dir / "tasks" / task_id / "raw" / "source.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video-bytes")
    commands: list[list[str]] = []
    _install_media_commands(monkeypatch, commands, duration="601.25")

    from app.db import session_scope
    from app.models import Artifact, WorkstationEvent
    from app.services.media_prep import prepare_media_for_asr

    with session_scope() as session:
        prepare_media_for_asr(session, task_id, video_path)
    commands.clear()

    with session_scope() as session:
        prepare_media_for_asr(session, task_id, video_path)

    with session_scope() as session:
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "media_prep")
        ).all()
        ready_events = session.exec(
            select(WorkstationEvent)
            .where(WorkstationEvent.entity_id == task_id)
            .where(WorkstationEvent.event_type == "artifact.ready")
        ).all()
        artifact_count = len(artifacts)
        artifact_kinds = {artifact.kind for artifact in artifacts}
        ready_event_count = len(ready_events)

    assert [command[0] for command in commands] == ["ffprobe"]
    assert artifact_count == 5
    assert artifact_kinds == {"media_probe", "media_chunk_manifest", "asr_audio_chunk"}
    assert ready_event_count == 5


def test_prepare_media_for_asr_rebuilds_all_chunk_audio_when_manifest_duration_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task("https://www.bilibili.com/video/BV1mn411c7mP", data_dir=data_dir, monkeypatch=monkeypatch)
    video_path = data_dir / "tasks" / task_id / "raw" / "source.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video-bytes")
    commands: list[list[str]] = []
    _install_media_commands(monkeypatch, commands, duration="601.25")

    from app.db import session_scope
    from app.models import Task, WorkstationEvent
    from app.services.media_prep import prepare_media_for_asr

    with session_scope() as session:
        prepare_media_for_asr(session, task_id, video_path)
    commands.clear()
    _install_media_commands(monkeypatch, commands, duration="900")

    with session_scope() as session:
        result = prepare_media_for_asr(session, task_id, video_path)

    with session_scope() as session:
        task = session.get(Task, task_id)
        ready_events = session.exec(
            select(WorkstationEvent)
            .where(WorkstationEvent.entity_id == task_id)
            .where(WorkstationEvent.event_type == "artifact.ready")
        ).all()
        storage_bytes = task.storage_bytes if task is not None else None

    actual_storage_bytes = sum(path.stat().st_size for path in (data_dir / "tasks" / task_id).rglob("*") if path.is_file())

    assert [(chunk.index, chunk.start_seconds, chunk.end_seconds) for chunk in result.chunk_manifest.chunks] == [
        (0, 0.0, 300.0),
        (1, 300.0, 600.0),
        (2, 600.0, 900.0),
    ]
    assert [command[0] for command in commands] == ["ffprobe", "ffmpeg", "ffmpeg", "ffmpeg"]
    assert [command[command.index("-ss") + 1] for command in commands[1:]] == ["0.0", "300.0", "600.0"]
    assert storage_bytes == actual_storage_bytes
    assert len(ready_events) == 5


def test_prepare_media_for_asr_regenerates_missing_or_invalid_chunk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task("https://www.bilibili.com/video/BV1mn411c7mP", data_dir=data_dir, monkeypatch=monkeypatch)
    video_path = data_dir / "tasks" / task_id / "raw" / "source.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video-bytes")
    commands: list[list[str]] = []
    _install_media_commands(monkeypatch, commands, duration="601.25")

    from app.db import session_scope
    from app.services.media_prep import prepare_media_for_asr

    with session_scope() as session:
        first_result = prepare_media_for_asr(session, task_id, video_path)
    first_result.chunk_manifest.chunks[1].audio_path.unlink()
    _write_wav(first_result.chunk_manifest.chunks[2].audio_path, duration_seconds=0.25)
    commands.clear()

    with session_scope() as session:
        prepare_media_for_asr(session, task_id, video_path)

    assert [command[0] for command in commands] == ["ffprobe", "ffmpeg", "ffmpeg"]
    assert [command[command.index("-ss") + 1] for command in commands[1:]] == ["300.0", "600.0"]


def test_prepare_media_for_asr_rejects_invalid_probe_duration_without_source_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task("https://www.bilibili.com/video/BV1mn411c7mP", data_dir=data_dir, monkeypatch=monkeypatch)
    video_path = data_dir / "tasks" / task_id / "raw" / "trusted-source.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video-bytes")
    commands: list[list[str]] = []
    _install_media_commands(monkeypatch, commands, duration="not-a-number")

    from app.db import session_scope
    from app.services.media_prep import MediaPrepFailure, prepare_media_for_asr

    with session_scope() as session, pytest.raises(MediaPrepFailure, match="ffprobe duration") as exc_info:
        prepare_media_for_asr(session, task_id, video_path, source_locator="https://safe.example/video")

    assert str(video_path) not in str(exc_info.value)
    assert [command[0] for command in commands] == ["ffprobe"]


def test_prepare_media_for_asr_redacts_ffmpeg_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task("https://www.bilibili.com/video/BV1mn411c7mP", data_dir=data_dir, monkeypatch=monkeypatch)
    video_path = data_dir / "tasks" / task_id / "raw" / "trusted-source.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video-bytes")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        match args[0]:
            case "ffprobe":
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"format": {"duration": "300"}}', stderr="")
            case "ffmpeg":
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=f"failed to read {video_path}")
            case unexpected:
                raise AssertionError(f"unexpected command: {unexpected}")

    monkeypatch.setattr("subprocess.run", fake_run)

    from app.db import session_scope
    from app.services.media_prep import MediaPrepFailure, prepare_media_for_asr

    with session_scope() as session, pytest.raises(MediaPrepFailure) as exc_info:
        prepare_media_for_asr(session, task_id, video_path, source_locator="https://safe.example/video")

    assert str(video_path) not in str(exc_info.value)
    assert "https://safe.example/video" in str(exc_info.value)


def test_prepare_media_for_asr_redacts_ffprobe_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task("https://www.bilibili.com/video/BV1mn411c7mP", data_dir=data_dir, monkeypatch=monkeypatch)
    video_path = data_dir / "tasks" / task_id / "raw" / "trusted-source.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video-bytes")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=f"failed to read {video_path}")

    monkeypatch.setattr("subprocess.run", fake_run)

    from app.db import session_scope
    from app.services.media_prep import MediaPrepFailure, prepare_media_for_asr

    with session_scope() as session, pytest.raises(MediaPrepFailure) as exc_info:
        prepare_media_for_asr(session, task_id, video_path, source_locator="https://safe.example/video")

    assert str(video_path) not in str(exc_info.value)
    assert "https://safe.example/video" in str(exc_info.value)
