from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from app.models import Task, utc_now
from app.services.storage import get_tasks_root


@dataclass(frozen=True, slots=True)
class WorkstationMetadataBackfillError(OSError):
    """Identifies managed task directories that could not be read during backfill."""

    task_ids: tuple[str, ...]

    def __str__(self) -> str:
        return f"Unable to backfill metadata for: {', '.join(self.task_ids)}"


def upgrade_database(database_url: str | None = None) -> None:
    """Upgrade a database and complete any pending metadata backfill."""
    from app.db import get_database_url

    resolved_url = database_url or get_database_url()
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", resolved_url)
    command.upgrade(config, "head")

    if _metadata_backfill_is_pending(resolved_url):
        _run_pending_metadata_backfill(resolved_url)


def _metadata_backfill_is_pending(database_url: str) -> bool:
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    with engine.connect() as connection:
        completed_at = connection.execute(
            text("SELECT completed_at FROM workstation_metadata_backfill WHERE id = 1")
        ).scalar_one()
    engine.dispose()
    return completed_at is None


def _run_pending_metadata_backfill(database_url: str) -> None:
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    try:
        with Session(engine) as session:
            try:
                backfill_workstation_metadata(session, get_tasks_root())
            except WorkstationMetadataBackfillError:
                session.commit()
                raise
            session.execute(
                text("UPDATE workstation_metadata_backfill SET completed_at = :completed_at WHERE id = 1"),
                {"completed_at": utc_now()},
            )
            session.commit()
    finally:
        engine.dispose()


def backfill_workstation_metadata(session: Session, tasks_root: Path) -> None:
    """Derive task titles and managed-directory storage totals for existing tasks."""
    failed_task_ids: list[str] = []
    for task in session.exec(select(Task)).all():
        try:
            task_root = tasks_root / task.id
            task.title = _task_title(task, task_root)
            task.storage_bytes = _directory_size(task_root)
        except OSError:
            failed_task_ids.append(task.id)
    if failed_task_ids:
        raise WorkstationMetadataBackfillError(tuple(failed_task_ids))


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
