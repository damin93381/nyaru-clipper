from __future__ import annotations

import sqlite3


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def test_init_db_adds_failure_code_column_to_existing_taskstage_schema(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{db_path}")
    _reset_runtime_state()

    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE taskstage (
                id INTEGER PRIMARY KEY,
                task_id VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                summary VARCHAR,
                attempts INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                started_at DATETIME,
                finished_at DATETIME
            );
            INSERT INTO taskstage (
                id, task_id, name, status, summary, attempts, created_at, updated_at
            ) VALUES (
                1, 'task-existing', 'translation', 'failed', 'provider_timeout', 1,
                '2026-06-16T00:00:00+00:00', '2026-06-16T00:01:00+00:00'
            );
            """
        )

    from app.db import init_db

    init_db()

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(taskstage)")}
        row = connection.execute(
            "SELECT task_id, name, status, summary, failure_code FROM taskstage WHERE id = 1"
        ).fetchone()

    assert "failure_code" in columns
    assert row == ("task-existing", "translation", "failed", "provider_timeout", None)
