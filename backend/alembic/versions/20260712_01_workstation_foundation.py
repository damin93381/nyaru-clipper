"""Add the additive workstation domain and legacy task projections.

Revision ID: 20260712_01
Revises:
Create Date: 2026-07-12 00:00:00
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import Column, DateTime, Integer, String, inspect, text
from sqlmodel import SQLModel, Session, select

from app.models import (
    CANONICAL_STAGES,
    MediaSource,
    PipelineRun,
    QueueEntry,
    QueueState,
    StageRun,
    Task,
    TaskStage,
)


revision = "20260712_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the workstation projection without replacing legacy task rows."""
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind)
    table_names = set(inspect(bind).get_table_names())
    task_columns = {column["name"] for column in inspect(bind).get_columns("task")}
    if "title" not in task_columns:
        op.add_column("task", Column("title", String(), nullable=True))
    if "archived_at" not in task_columns:
        op.add_column("task", Column("archived_at", DateTime(timezone=True), nullable=True))
    if "storage_bytes" not in task_columns:
        op.add_column(
            "task",
            Column("storage_bytes", Integer(), nullable=False, server_default="0"),
        )
    if "taskstage" in table_names:
        stage_columns = {column["name"] for column in inspect(bind).get_columns("taskstage")}
        if "failure_code" not in stage_columns:
            op.add_column("taskstage", Column("failure_code", String(), nullable=True))

    _create_task_search(bind)
    _backfill_workstation_records(bind)


def downgrade() -> None:
    """Remove only additive workstation structures."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for trigger_name in (
            "task_search_task_delete",
            "task_search_task_insert",
            "task_search_task_update",
            "task_search_source_delete",
            "task_search_source_insert",
            "task_search_source_update",
        ):
            bind.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name}"))
        bind.execute(text("DROP TABLE IF EXISTS task_search"))
    for table_name in ("stagerun", "pipelinerun", "queueentry", "queuestate", "tasktaglink", "tasktag", "mediasource"):
        bind.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


def _create_task_search(bind) -> None:
    if bind.dialect.name != "sqlite":
        return
    bind.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS task_search "
            "USING fts5(task_id UNINDEXED, title, source_identity)"
        )
    )
    bind.execute(text("DELETE FROM task_search"))
    bind.execute(
        text(
            "INSERT INTO task_search (task_id, title, source_identity) "
            "SELECT id, COALESCE(title, ''), source_url FROM task"
        )
    )
    _create_search_triggers(bind)


def _create_search_triggers(bind) -> None:
    trigger_sql = {
        "task_search_task_insert": """
            CREATE TRIGGER IF NOT EXISTS task_search_task_insert AFTER INSERT ON task BEGIN
                INSERT INTO task_search (task_id, title, source_identity)
                VALUES (new.id, COALESCE(new.title, ''), new.source_url);
            END
        """,
        "task_search_task_update": """
            CREATE TRIGGER IF NOT EXISTS task_search_task_update AFTER UPDATE OF title, source_url ON task BEGIN
                DELETE FROM task_search WHERE task_id = old.id;
                INSERT INTO task_search (task_id, title, source_identity)
                VALUES (new.id, COALESCE(new.title, ''), new.source_url);
            END
        """,
        "task_search_task_delete": """
            CREATE TRIGGER IF NOT EXISTS task_search_task_delete AFTER DELETE ON task BEGIN
                DELETE FROM task_search WHERE task_id = old.id;
            END
        """,
        "task_search_source_insert": """
            CREATE TRIGGER IF NOT EXISTS task_search_source_insert AFTER INSERT ON mediasource BEGIN
                DELETE FROM task_search WHERE task_id = new.task_id;
                INSERT INTO task_search (task_id, title, source_identity)
                SELECT id, COALESCE(title, ''), new.locator FROM task WHERE id = new.task_id;
            END
        """,
        "task_search_source_update": """
            CREATE TRIGGER IF NOT EXISTS task_search_source_update AFTER UPDATE OF locator ON mediasource BEGIN
                DELETE FROM task_search WHERE task_id = old.task_id;
                INSERT INTO task_search (task_id, title, source_identity)
                SELECT id, COALESCE(title, ''), new.locator FROM task WHERE id = new.task_id;
            END
        """,
        "task_search_source_delete": """
            CREATE TRIGGER IF NOT EXISTS task_search_source_delete AFTER DELETE ON mediasource BEGIN
                DELETE FROM task_search WHERE task_id = old.task_id;
                INSERT INTO task_search (task_id, title, source_identity)
                SELECT id, COALESCE(title, ''), source_url FROM task WHERE id = old.task_id;
            END
        """,
    }
    for statement in trigger_sql.values():
        bind.execute(text(statement))


def _backfill_workstation_records(bind) -> None:
    with Session(bind=bind) as session:
        if session.get(QueueState, 1) is None:
            session.add(QueueState())
        for position, task in enumerate(session.exec(select(Task).order_by(Task.created_at)), start=1):
            _backfill_task_projection(session, task, position)
        session.commit()


def _backfill_task_projection(session: Session, task: Task, position: int) -> None:
    if session.exec(select(MediaSource).where(MediaSource.task_id == task.id)).first() is None:
        session.add(
            MediaSource(
                task_id=task.id,
                kind="bilibili" if "bilibili.com" in task.normalized_source_url else "local",
                locator=task.source_url,
                source_video_id=task.source_video_id,
            )
        )
    if session.get(QueueEntry, task.id) is None:
        match task.status:
            case "running":
                queue_state = "running"
            case "pending":
                queue_state = "queued"
            case _:
                queue_state = "finished"
        session.add(
            QueueEntry(
                task_id=task.id,
                position=position,
                state=queue_state,
            )
        )
    run_id = f"legacy:{task.id}"
    if session.get(PipelineRun, run_id) is None:
        session.add(
            PipelineRun(
                id=run_id,
                task_id=task.id,
                status=task.status,
                trigger="migration",
                created_at=task.created_at,
                started_at=task.created_at if task.status != "pending" else None,
                finished_at=task.updated_at if task.status in {"success", "failed", "cancelled"} else None,
            )
        )
        stage_by_name = {stage.name: stage for stage in session.exec(select(TaskStage).where(TaskStage.task_id == task.id))}
        for stage_name in CANONICAL_STAGES:
            legacy_stage = stage_by_name.get(stage_name)
            session.add(
                StageRun(
                    run_id=run_id,
                    name=stage_name,
                    status=legacy_stage.status if legacy_stage is not None else "pending",
                    summary=legacy_stage.summary if legacy_stage is not None else None,
                    failure_code=legacy_stage.failure_code if legacy_stage is not None else None,
                    attempts=legacy_stage.attempts if legacy_stage is not None else 0,
                    started_at=legacy_stage.started_at if legacy_stage is not None else None,
                    finished_at=legacy_stage.finished_at if legacy_stage is not None else None,
                )
            )
