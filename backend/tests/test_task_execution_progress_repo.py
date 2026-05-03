from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def _configure_env(data_dir: Path, db_path: Path) -> None:
    import os

    os.environ["APP_DATA_DIR"] = str(data_dir)
    os.environ["APP_DATABASE_URL"] = f"sqlite:///{db_path}"
    _reset_runtime_state()


def test_upsert_and_clear_task_execution_progress_round_trip(tmp_path) -> None:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "task-state.sqlite3"
    _configure_env(data_dir, db_path)

    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task
    import app.repositories.tasks as task_repo

    upsert_progress = getattr(task_repo, "upsert_task_execution_progress", None)
    clear_progress = getattr(task_repo, "clear_task_execution_progress", None)
    get_detail = getattr(task_repo, "get_task_detail", None)

    assert upsert_progress is not None
    assert clear_progress is not None
    assert get_detail is not None

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, "https://www.bilibili.com/video/BV1repo001")
        task_id = payload["task_id"]

    with session_scope() as session:
        upsert_progress(
            session,
            task_id=task_id,
            stage_name="asr",
            current_phase="model_load",
            phase_index=1,
            phase_count=5,
            latest_message="loading model",
            phase_started_at=datetime(2026, 5, 3, 6, 0, tzinfo=timezone.utc),
            heartbeat_at=datetime(2026, 5, 3, 6, 1, tzinfo=timezone.utc),
            phase_timings=[
                {"name": "model_load", "status": "running", "elapsed_ms": 250},
            ],
        )

    with session_scope() as session:
        detail = get_detail(session, task_id)

    assert detail is not None
    assert detail["execution_progress"]["current_phase"] == "model_load"
    assert detail["execution_progress"]["phases"] == [
        {"name": "model_load", "status": "running", "elapsed_ms": 250},
    ]

    with session_scope() as session:
        clear_progress(session, task_id=task_id)

    with session_scope() as session:
        detail = get_detail(session, task_id)

    assert detail is not None
    assert "execution_progress" not in detail
