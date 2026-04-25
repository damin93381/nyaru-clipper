from __future__ import annotations

from pathlib import Path


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def _create_task(data_dir: Path, monkeypatch, *, status: str) -> str:
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{data_dir.parent / 'task-state.sqlite3'}")
    _reset_runtime_state()

    from app.db import init_db, session_scope
    from app.models import Task
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, "https://www.bilibili.com/video/BV1ef411c7mG")
        task = session.get(Task, payload["task_id"])
        assert task is not None
        task.status = status
        session.add(task)
        return payload["task_id"]


def test_cleanup_prunes_only_transient_work_artifacts(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task(data_dir, monkeypatch, status="success")
    task_root = data_dir / "tasks" / task_id

    preserved_paths = [
        task_root / "raw" / "source.mp4",
        task_root / "exports" / "clip-00012000-00019500.mp4",
        task_root / "reports" / "task-report.md",
        task_root / "logs" / "export.log",
        task_root / "work" / "media-probe.json",
        task_root / "work" / "asr-segments.json",
        task_root / "work" / "subtitles.zh.srt",
        task_root / "work" / "subtitles.zh-ja.json",
        task_root / "work" / "subtitles.zh-ja.srt",
        task_root / "work" / "highlight-candidates.json",
    ]
    transient_paths = [
        task_root / "work" / "asr-input.wav",
        task_root / "work" / "asr-alignment-raw.json",
        task_root / "work" / "audio-energy.json",
    ]

    for path in preserved_paths + transient_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")

    from app.services.cleanup import cleanup_task_artifacts

    result = cleanup_task_artifacts(task_id)

    assert sorted(path.name for path in result.deleted_paths) == sorted(path.name for path in transient_paths)
    assert all(path.exists() for path in preserved_paths)
    assert all(not path.exists() for path in transient_paths)


def test_cleanup_skips_non_successful_tasks(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task(data_dir, monkeypatch, status="failed")
    transient_path = data_dir / "tasks" / task_id / "work" / "asr-input.wav"
    transient_path.parent.mkdir(parents=True, exist_ok=True)
    transient_path.write_text("fixture", encoding="utf-8")

    from app.services.cleanup import cleanup_task_artifacts

    result = cleanup_task_artifacts(task_id)

    assert result.deleted_paths == []
    assert transient_path.exists()
