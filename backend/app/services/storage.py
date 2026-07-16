from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import Artifact, Task
from app.paths import get_data_dir


def build_artifact_content_path(*, task_id: str, artifact_id: int, artifact_path: str | Path) -> str:
    filename = Path(artifact_path).name
    return f"/api/tasks/{task_id}/artifacts/{artifact_id}/content/{filename}"


def get_tasks_root() -> Path:
    root = get_data_dir() / "tasks"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_task_root(task_id: str) -> Path:
    root = get_tasks_root() / task_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_task_dirs(task_id: str) -> dict[str, Path]:
    task_root = get_task_root(task_id)
    task_dirs = {
        "raw": task_root / "raw",
        "work": task_root / "work",
        "exports": task_root / "exports",
        "reports": task_root / "reports",
        "logs": task_root / "logs",
    }
    for path in task_dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return task_dirs


def log_file_for_stage(task_id: str, stage_name: str) -> Path:
    task_dirs = ensure_task_dirs(task_id)
    return task_dirs["logs"] / f"{stage_name}.log"


def summarize_stage_log(task_id: str, stage_name: str) -> str | None:
    log_path = log_file_for_stage(task_id, stage_name)
    if not log_path.exists():
        return None
    lines = [line.strip() for line in log_path.read_text().splitlines() if line.strip()]
    return lines[-1] if lines else None


def resolve_task_artifact_path(task_id: str, artifact_path: str | Path) -> Path:
    candidate = Path(artifact_path).resolve()
    task_root = get_task_root(task_id).resolve()
    candidate.relative_to(task_root)
    return candidate


def persist_artifact_metadata(
    session: Session,
    *,
    task_id: str,
    stage_name: str,
    kind: str,
    path: Path,
    metadata: dict[str, Any] | None = None,
) -> Artifact:
    artifact = Artifact(
        task_id=task_id,
        stage_name=stage_name,
        kind=kind,
        path=str(path),
        metadata_json=json.dumps(metadata or {}, sort_keys=True),
    )
    session.add(artifact)
    session.flush()
    task = session.get(Task, task_id)
    if task is not None:
        task.storage_bytes = sum(
            candidate.stat().st_size
            for candidate in get_task_root(task_id).rglob("*")
            if candidate.is_file()
        )
        session.add(task)
    session.refresh(artifact)
    if artifact.id is None:
        raise RuntimeError("Persisted artifact is missing its ID")
    from app.services.workstation_events import publish_event

    publish_event(
        session,
        "artifact.ready",
        task_id,
        {
            "task_id": task_id,
            "artifact_id": artifact.id,
            "stage_name": stage_name,
            "kind": kind,
            "path": build_artifact_content_path(
                task_id=task_id,
                artifact_id=artifact.id,
                artifact_path=path,
            ),
        },
    )
    return artifact


def invalidate_translation_artifacts(session: Session, *, task_id: str) -> None:
    """Remove retry-invalid translation outputs while preserving reusable ASR and chunk caches."""
    artifacts = session.exec(
        select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "translation")
    ).all()
    for artifact in artifacts:
        try:
            artifact_path = resolve_task_artifact_path(task_id, artifact.path)
        except ValueError:
            artifact_path = None
        if artifact_path is not None:
            artifact_path.unlink(missing_ok=True)
        session.delete(artifact)

    work_dir = ensure_task_dirs(task_id)["work"]
    for filename in (
        "subtitles.zh-ja.preproofread.json",
        "subtitles.zh-ja.preproofread.srt",
        "proofread-audit.json",
        "subtitles.zh-ja.json",
        "subtitles.zh-ja.srt",
    ):
        (work_dir / filename).unlink(missing_ok=True)

    task = session.get(Task, task_id)
    if task is not None:
        task.storage_bytes = sum(
            candidate.stat().st_size
            for candidate in get_task_root(task_id).rglob("*")
            if candidate.is_file()
        )
        session.add(task)
