from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sqlmodel import select


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def _create_task(source_url: str, *, data_dir: Path, monkeypatch) -> str:
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{data_dir.parent / 'task-state.sqlite3'}")
    _reset_runtime_state()

    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, source_url)
        return payload["task_id"]


def test_media_prep_captures_ffprobe_and_extracts_mono_wav(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task("https://www.bilibili.com/video/BV1mn411c7mP", data_dir=data_dir, monkeypatch=monkeypatch)
    video_path = data_dir / "tasks" / task_id / "raw" / "source.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video-bytes")
    commands: list[list[str]] = []

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(list(args))
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    {
                        "format": {"duration": "55.2", "bit_rate": "320000"},
                        "streams": [
                            {"codec_type": "video", "width": 1920, "height": 1080},
                            {"codec_type": "audio", "sample_rate": "48000", "channels": 2},
                        ],
                    }
                ),
                stderr="",
            )
        if args[0] == "ffmpeg":
            output_path = Path(args[-1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"wav-bytes")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("subprocess.run", fake_run)

    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.media_prep import prepare_media_for_asr

    with session_scope() as session:
        result = prepare_media_for_asr(session, task_id, video_path)

    assert [command[0] for command in commands] == ["ffprobe", "ffmpeg"]
    assert result.source_video_path == video_path
    assert result.audio_path == data_dir / "tasks" / task_id / "work" / "asr-input.wav"
    assert result.audio_path.exists()
    assert result.ffprobe_metadata["format"]["duration"] == "55.2"

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "media_prep")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "media_prep")
        ).all()
        stage_status = stage.status
        stage_summary = stage.summary
        artifact_kinds = {artifact.kind for artifact in artifacts}

    assert stage_status == "success"
    assert stage_summary == "Prepared ffprobe metadata and ASR wav"
    assert artifact_kinds == {"asr_audio", "media_probe"}
