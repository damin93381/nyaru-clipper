from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.db import session_scope
from app.models import Task
from app.services.storage import ensure_task_dirs


@dataclass(slots=True)
class CleanupResult:
    task_id: str
    deleted_paths: list[Path]


def cleanup_task_artifacts(task_id: str) -> CleanupResult:
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise ValueError(f"Unknown task_id: {task_id}")
        if task.status != "success":
            return CleanupResult(task_id=task_id, deleted_paths=[])

    task_dirs = ensure_task_dirs(task_id)
    work_dir = task_dirs["work"]
    deleted_paths: list[Path] = []
    if not work_dir.exists():
        return CleanupResult(task_id=task_id, deleted_paths=[])

    for path in sorted(work_dir.rglob("*"), reverse=True):
        if path.is_file() and not _should_preserve_work_path(path):
            path.unlink()
            deleted_paths.append(path)

    for path in sorted(work_dir.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass

    return CleanupResult(task_id=task_id, deleted_paths=deleted_paths)


def _should_preserve_work_path(path: Path) -> bool:
    name = path.name
    if name in {"media-probe.json", "asr-segments.json", "highlight-candidates.json"}:
        return True
    if name.startswith("subtitles."):
        return True
    if "manifest" in name or "metadata" in name:
        return True
    return False
