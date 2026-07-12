from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import Session, select

from app.models import Task
from app.services.storage import get_tasks_root


def upgrade_database(database_url: str | None = None) -> None:
    """Upgrade a database to the workstation schema and backfill its metadata once."""
    from app.db import get_database_url
    from sqlmodel import create_engine

    resolved_url = database_url or get_database_url()
    engine = create_engine(resolved_url, connect_args={"check_same_thread": False})
    inspector = inspect(engine)
    is_initial_upgrade = "alembic_version" not in inspector.get_table_names()
    if not is_initial_upgrade:
        with engine.connect() as connection:
            is_initial_upgrade = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none() is None
    engine.dispose()

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", resolved_url)
    command.upgrade(config, "head")

    if is_initial_upgrade:
        metadata_engine = create_engine(resolved_url, connect_args={"check_same_thread": False})
        with Session(metadata_engine) as session:
            backfill_workstation_metadata(session, get_tasks_root())
            session.commit()
        metadata_engine.dispose()


def backfill_workstation_metadata(session: Session, tasks_root: Path) -> None:
    """Derive task titles and managed-directory storage totals for existing tasks."""
    for task in session.exec(select(Task)).all():
        task_root = tasks_root / task.id
        task.title = _task_title(task, task_root)
        task.storage_bytes = _directory_size(task_root)


def _task_title(task: Task, task_root: Path) -> str:
    metadata_path = task_root / "raw" / "source-metadata.json"
    metadata_title = _metadata_title(metadata_path)
    if metadata_title is not None:
        return metadata_title
    if task.source_video_id:
        return task.source_video_id
    return task.source_url


def _metadata_title(metadata_path: Path) -> str | None:
    if not metadata_path.is_file():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    title = payload.get("title")
    if not isinstance(title, str):
        return None
    return title.strip() or None


def _directory_size(task_root: Path) -> int:
    if not task_root.is_dir():
        return 0
    return sum(path.stat().st_size for path in task_root.rglob("*") if path.is_file())
