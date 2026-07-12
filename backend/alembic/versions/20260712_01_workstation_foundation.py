"""Add the additive workstation domain and legacy task projections.

Revision ID: 20260712_01
Revises:
Create Date: 2026-07-12 00:00:00
"""
from __future__ import annotations

# allow: SIZE_OK — immutable explicit Alembic baseline schema declaration.
from alembic import op
import sqlalchemy as sa
from sqlmodel import Session, select

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
    table_names = set(sa.inspect(bind).get_table_names())
    if "task" not in table_names:
        _create_task_table()
    else:
        _add_task_columns(bind)
    if "taskstage" in table_names:
        _add_failure_code_column(bind)

    _create_workstation_tables()
    _create_task_search(bind)
    _backfill_workstation_records(bind)


def downgrade() -> None:
    """Remove the new tables while preserving additive legacy-table columns.

    The task and taskstage columns stay in place to avoid destructive SQLite table
    rebuilds during a rollback after users have written workstation metadata.
    """
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
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger_name}"))
        bind.execute(sa.text("DROP TABLE IF EXISTS task_search"))
    for table_name in (
        "workstation_metadata_backfill",
        "stagerun",
        "pipelinerun",
        "queueentry",
        "queuestate",
        "tasktaglink",
        "tasktag",
        "mediasource",
    ):
        bind.execute(sa.text(f"DROP TABLE IF EXISTS {table_name}"))


def _create_task_table() -> None:
    op.create_table(
        "task",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("normalized_source_url", sa.String(), nullable=False),
        sa.Column("source_video_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("storage_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_normalized_source_url", "task", ["normalized_source_url"])
    op.create_index("ix_task_source_video_id", "task", ["source_video_id"])
    op.create_index("ix_task_status", "task", ["status"])


def _add_task_columns(bind) -> None:
    task_columns = {column["name"] for column in sa.inspect(bind).get_columns("task")}
    if "title" not in task_columns:
        op.add_column("task", sa.Column("title", sa.String(), nullable=True))
    if "archived_at" not in task_columns:
        op.add_column("task", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    if "storage_bytes" not in task_columns:
        op.add_column(
            "task",
            sa.Column("storage_bytes", sa.Integer(), nullable=False, server_default="0"),
        )


def _add_failure_code_column(bind) -> None:
    stage_columns = {column["name"] for column in sa.inspect(bind).get_columns("taskstage")}
    if "failure_code" not in stage_columns:
        op.add_column("taskstage", sa.Column("failure_code", sa.String(), nullable=True))


def _create_workstation_tables() -> None:
    op.create_table(
        "mediasource",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("locator", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("source_video_id", sa.String(), nullable=True),
        sa.Column("import_mode", sa.String(), nullable=False, server_default="managed"),
        sa.Column("metadata_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_mediasource_task_id"),
    )
    op.create_index("ix_mediasource_task_id", "mediasource", ["task_id"])
    op.create_index("ix_mediasource_kind", "mediasource", ["kind"])
    op.create_index("ix_mediasource_source_video_id", "mediasource", ["source_video_id"])

    op.create_table(
        "tasktag",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "tasktaglink",
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("tag_name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["tag_name"], ["tasktag.name"]),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("task_id", "tag_name"),
        sa.UniqueConstraint("task_id", "tag_name", name="uq_tasktaglink_task_tag"),
    )

    op.create_table(
        "queuestate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "queueentry",
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index("ix_queueentry_position", "queueentry", ["position"])
    op.create_index("ix_queueentry_priority", "queueentry", ["priority"])
    op.create_index("ix_queueentry_state", "queueentry", ["state"])

    op.create_table(
        "pipelinerun",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False, server_default="create"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipelinerun_task_id", "pipelinerun", ["task_id"])
    op.create_index("ix_pipelinerun_status", "pipelinerun", ["status"])

    op.create_table(
        "stagerun",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["pipelinerun.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stagerun_run_id", "stagerun", ["run_id"])
    op.create_index("ix_stagerun_name", "stagerun", ["name"])
    op.create_index("ix_stagerun_status", "stagerun", ["status"])
    op.create_index("ix_stagerun_failure_code", "stagerun", ["failure_code"])

    op.create_table(
        "workstation_metadata_backfill",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(sa.text("INSERT INTO workstation_metadata_backfill (id) VALUES (1)"))


def _create_task_search(bind) -> None:
    if bind.dialect.name != "sqlite":
        return
    bind.execute(
        sa.text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS task_search "
            "USING fts5(task_id UNINDEXED, title, source_identity)"
        )
    )
    bind.execute(sa.text("DELETE FROM task_search"))
    bind.execute(
        sa.text(
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
        bind.execute(sa.text(statement))


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
        session.add(QueueEntry(task_id=task.id, position=position, state=queue_state))
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
