from __future__ import annotations

import json
import subprocess
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


def test_bbdown_success_persists_normalized_artifacts(backend_env, monkeypatch) -> None:
    cookie_path = Path(backend_env["data_dir"]) / "cookies.txt"
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_path.write_text("SESSDATA=test\n")
    monkeypatch.setenv("APP_BILIBILI_COOKIE_PATH", str(cookie_path))

    task_id = _create_task("https://www.bilibili.com/video/BV1xx411c7mD?p=1")
    commands: list[list[str]] = []

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(list(args))
        if args[0] == "BBDown":
            output_path = Path(backend_env["data_dir"]) / "tasks" / task_id / "raw" / "source.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"video-bytes")
            metadata = {
                "title": "Test Stream",
                "uploader": "Streamer",
                "source_video_id": "BV1xx411c7mD",
                "duration_seconds": 321.5,
            }
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(metadata),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("subprocess.run", fake_run)

    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.downloader import download_bilibili_vod

    with session_scope() as session:
        result = download_bilibili_vod(session, task_id)

    assert commands and commands[0][0] == "BBDown"
    assert result.selected_downloader == "bbdown"
    assert result.fallback_used is False
    assert result.auth_cookie_present is True
    assert result.output_path.name == "source.mp4"
    assert result.output_path.exists()
    assert result.source_metadata == {
        "duration_seconds": 321.5,
        "source_video_id": "BV1xx411c7mD",
        "title": "Test Stream",
        "uploader": "Streamer",
    }

    with session_scope() as session:
        ingest_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "ingest")
        ).all()
        ingest_status = ingest_stage.status
        ingest_summary = ingest_stage.summary
        artifact_kinds = {artifact.kind for artifact in artifacts}

    assert ingest_status == "success"
    assert ingest_summary == "Downloaded source video via bbdown"
    assert artifact_kinds == {"source_metadata", "source_video"}


def test_bbdown_failure_falls_back_to_ytdlp(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1xy411c7mE")
    commands: list[list[str]] = []

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(list(args))
        if args[0] == "BBDown":
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="bbdown transient failure")
        if args[0] == "yt-dlp":
            output_path = Path(backend_env["data_dir"]) / "tasks" / task_id / "raw" / "source.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"video-bytes")
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    {
                        "id": "BV1xy411c7mE",
                        "title": "Fallback Stream",
                        "uploader": "Backup Streamer",
                        "duration": 88.0,
                    }
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("subprocess.run", fake_run)

    from app.db import session_scope
    from app.models import TaskStage
    from app.services.downloader import download_bilibili_vod

    with session_scope() as session:
        result = download_bilibili_vod(session, task_id)

    assert [command[0] for command in commands] == ["BBDown", "yt-dlp"]
    assert result.selected_downloader == "yt-dlp"
    assert result.fallback_used is True
    assert result.auth_cookie_present is False
    assert result.source_metadata == {
        "duration_seconds": 88.0,
        "source_video_id": "BV1xy411c7mE",
        "title": "Fallback Stream",
        "uploader": "Backup Streamer",
    }

    with session_scope() as session:
        ingest_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        ingest_status = ingest_stage.status
        ingest_summary = ingest_stage.summary

    assert ingest_status == "success"
    assert ingest_summary == "Downloaded source video via yt-dlp (fallback)"


@pytest.mark.parametrize(
    ("stderr_text", "expected_code"),
    [
        ("ERROR: This video is private", "private_or_region_locked"),
        ("login required to access this video", "auth_missing"),
    ],
)
def test_classifies_access_failures_without_fallback(
    backend_env,
    monkeypatch,
    stderr_text: str,
    expected_code: str,
) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1zz411c7mF")
    commands: list[list[str]] = []

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=stderr_text)

    monkeypatch.setattr("subprocess.run", fake_run)

    from app.db import session_scope
    from app.models import TaskStage
    from app.services.downloader import DownloaderFailure, download_bilibili_vod

    with pytest.raises(DownloaderFailure) as exc_info:
        with session_scope() as session:
            download_bilibili_vod(session, task_id)

    assert [command[0] for command in commands] == ["BBDown"]
    assert exc_info.value.code == expected_code

    with session_scope() as session:
        ingest_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        ingest_status = ingest_stage.status
        ingest_summary = ingest_stage.summary

    assert ingest_status == "failed"
    assert expected_code in (ingest_summary or "")
