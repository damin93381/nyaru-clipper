from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sqlmodel import Session, select


def _create_legacy_database(db_path: Path, task_id: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE task (
                id VARCHAR PRIMARY KEY,
                source_url VARCHAR NOT NULL,
                normalized_source_url VARCHAR NOT NULL,
                source_video_id VARCHAR,
                status VARCHAR NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE taskjob (
                id INTEGER PRIMARY KEY,
                task_id VARCHAR NOT NULL,
                stage_name VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                gpu_bound BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                started_at DATETIME,
                finished_at DATETIME
            );
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
            """
        )
        connection.execute(
            """
            INSERT INTO task (
                id, source_url, normalized_source_url, source_video_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                "https://www.bilibili.com/video/BV1legacy001",
                "https://www.bilibili.com/video/BV1legacy001",
                "BV1legacy001",
                "success",
                "2026-07-12T00:00:00+00:00",
                "2026-07-12T00:01:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO taskjob (
                id, task_id, stage_name, status, gpu_bound, created_at, updated_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                7,
                task_id,
                "report",
                "success",
                True,
                "2026-07-12T00:00:00+00:00",
                "2026-07-12T00:01:00+00:00",
                "2026-07-12T00:00:00+00:00",
                "2026-07-12T00:01:00+00:00",
            ),
        )
        for index, stage_name in enumerate(
            ("ingest", "media_prep", "asr", "translation", "highlight", "export", "report"),
            start=1,
        ):
            connection.execute(
                """
                INSERT INTO taskstage (
                    id, task_id, name, status, summary, attempts, created_at, updated_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    index,
                    task_id,
                    stage_name,
                    "success",
                    f"{stage_name} complete",
                    1,
                    "2026-07-12T00:00:00+00:00",
                    "2026-07-12T00:01:00+00:00",
                    "2026-07-12T00:00:00+00:00",
                    "2026-07-12T00:01:00+00:00",
                ),
            )


def test_upgrade_database_backfills_workstation_domain_from_legacy_schema(tmp_path: Path, monkeypatch) -> None:
    # Given: a current pre-v2 database and its managed task directory.
    database_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    task_id = "task-legacy"
    _create_legacy_database(database_path, task_id)
    task_root = tmp_path / "data" / "tasks" / task_id
    raw_dir = task_root / "raw"
    raw_dir.mkdir(parents=True)
    metadata_path = raw_dir / "source-metadata.json"
    metadata_path.write_text(
        json.dumps({"title": "Legacy Fixture Stream", "source_video_id": "BV1legacy001"}),
        encoding="utf-8",
    )
    payload_path = raw_dir / "source.mp4"
    payload_path.write_bytes(b"fixture-video")
    expected_task_directory_size = sum(
        path.stat().st_size for path in task_root.rglob("*") if path.is_file()
    )

    # When: the Alembic database upgrade is run twice.
    from app.db_migrations import upgrade_database

    database_url = f"sqlite:///{database_path}"
    upgrade_database(database_url)
    upgrade_database(database_url)

    # Then: legacy IDs remain stable and the workstation projection is complete.
    from app.db import get_engine, reset_db_runtime
    from app.models import (
        CANONICAL_STAGES,
        MediaSource,
        PipelineRun,
        QueueEntry,
        QueueState,
        StageRun,
        Task,
    )

    reset_db_runtime()
    with Session(get_engine()) as session:
        migrated_task = session.get(Task, task_id)
        media_source = session.exec(select(MediaSource).where(MediaSource.task_id == task_id)).one()
        queue_entry = session.get(QueueEntry, task_id)
        queue_state = session.get(QueueState, 1)
        pipeline_run = session.exec(select(PipelineRun).where(PipelineRun.task_id == task_id)).one()
        stage_runs = session.exec(
            select(StageRun).where(StageRun.run_id == pipeline_run.id).order_by(StageRun.id)
        ).all()

    assert migrated_task is not None
    assert migrated_task.id == task_id
    assert media_source.task_id == task_id
    assert media_source.kind == "bilibili"
    assert queue_entry is not None
    assert queue_entry.task_id == task_id
    assert queue_entry.state in {"queued", "running", "finished"}
    assert queue_state is not None
    assert queue_state.id == 1
    assert queue_state.revision >= 1
    assert pipeline_run.task_id == task_id
    assert [item.name for item in stage_runs] == CANONICAL_STAGES
    assert migrated_task.title
    assert migrated_task.storage_bytes == expected_task_directory_size
    with sqlite3.connect(database_path) as connection:
        search_row = connection.execute(
            "SELECT task_id, title, source_identity FROM task_search WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    assert search_row == (task_id, "Legacy Fixture Stream", "https://www.bilibili.com/video/BV1legacy001")


def test_persist_artifact_metadata_recomputes_task_storage_bytes(tmp_path: Path, monkeypatch) -> None:
    # Given: an initialized workstation database and a managed artifact file.
    database_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    from app.db import get_engine, init_db, reset_db_runtime
    from app.models import Task
    from app.services.storage import get_task_root, persist_artifact_metadata

    reset_db_runtime()
    init_db()
    task_id = "task-artifact"
    artifact_path = get_task_root(task_id) / "reports" / "summary.md"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"storage-total")
    with Session(get_engine()) as session:
        session.add(
            Task(
                id=task_id,
                source_url="file:///fixture.mp4",
                normalized_source_url="file:///fixture.mp4",
            )
        )
        session.commit()

        # When: its artifact metadata is persisted.
        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="report",
            kind="report",
            path=artifact_path,
        )
        session.commit()

        # Then: the task's persisted total reflects the managed directory.
        task = session.get(Task, task_id)

    assert task is not None
    assert task.storage_bytes == artifact_path.stat().st_size
