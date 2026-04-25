from pathlib import Path


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def test_ensure_task_dirs_creates_canonical_layout(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    _reset_runtime_state()

    from app.services.storage import ensure_task_dirs

    task_dirs = ensure_task_dirs("task-demo")

    assert sorted(task_dirs.keys()) == ["exports", "logs", "raw", "reports", "work"]
    assert all(Path(path).is_dir() for path in task_dirs.values())
    assert {Path(path).parent.name for path in task_dirs.values()} == {"task-demo"}
    assert {Path(path).name for path in task_dirs.values()} == set(task_dirs.keys())
