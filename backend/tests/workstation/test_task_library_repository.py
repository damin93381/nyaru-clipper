from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select


def _reset_runtime_state() -> None:
    from app.db import reset_db_runtime

    reset_db_runtime()


@pytest.fixture()
def session(tmp_path, monkeypatch) -> Session:
    # Given: an isolated, migrated workstation database.
    database_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    _reset_runtime_state()

    from app.db import get_engine, init_db

    init_db()
    with Session(get_engine()) as database_session:
        yield database_session


def _seed_library(session: Session) -> None:
    from app.models import MediaSource, Task, TaskTag, TaskTagLink

    base_time = datetime(2026, 7, 12, tzinfo=timezone.utc)
    session.add_all([TaskTag(name="summer"), TaskTag(name="music")])
    for index in range(1_025):
        status = ("pending", "running", "success", "failed", "cancelled")[index % 5]
        title = f"夏日 task {index:04d}" if status in {"running", "failed"} else f"Winter task {index:04d}"
        task_id = f"task-{index:04d}"
        task = Task(
            id=task_id,
            source_url=f"file:///fixtures/{task_id}.mp4",
            normalized_source_url=f"file:///fixtures/{task_id}.mp4",
            status=status,
            title=title,
            archived_at=base_time if index % 97 == 0 else None,
            storage_bytes=index,
            created_at=base_time + timedelta(minutes=index),
            updated_at=base_time + timedelta(minutes=index // 2),
        )
        session.add(task)
        session.add(
            MediaSource(
                task_id=task_id,
                kind="bilibili" if index % 2 == 0 else "local",
                locator=task.source_url,
                display_name=f"Source {index:04d}",
            )
        )
        if index % 10 == 0:
            session.add(TaskTagLink(task_id=task_id, tag_name="summer"))
        if index % 15 == 0:
            session.add(TaskTagLink(task_id=task_id, tag_name="music"))
    session.commit()


def test_list_workstation_tasks_filters_pages_and_clamps_results(session: Session) -> None:
    # Given: more than one page of mixed workstation tasks.
    _seed_library(session)
    from app.api.schemas.workstation import TaskListQuery
    from app.repositories.workstation import list_workstation_tasks

    # When: a filtered page is requested.
    page = list_workstation_tasks(
        session,
        TaskListQuery(query="夏日", statuses=["running", "failed"], page=2, page_size=50),
    )

    # Then: filtering happens before the bounded server-side page is returned.
    assert page.page == 2
    assert page.page_size == 50
    assert page.total >= len(page.items)
    assert all("夏日" in item.title for item in page.items)
    assert all(item.status in {"running", "failed"} for item in page.items)
    assert len(page.items) <= 50

    # When: a client requests a page larger than the public maximum.
    clamped_page = list_workstation_tasks(session, TaskListQuery(page=1, page_size=500))

    # Then: the repository clamps it before issuing the SQL page query.
    assert clamped_page.page_size == 100
    assert len(clamped_page.items) == 100


def test_list_workstation_tasks_uses_stable_order_tags_and_archive_default(session: Session) -> None:
    # Given: tasks with tied timestamps, tags, and one archived match.
    _seed_library(session)
    from app.api.schemas.workstation import TaskListQuery
    from app.models import Task
    from app.repositories.workstation import list_workstation_tasks

    tied_time = datetime(2026, 8, 1, tzinfo=timezone.utc)
    for task_id in ("task-0010", "task-0020"):
        task = session.get(Task, task_id)
        assert task is not None
        task.updated_at = tied_time
    archived = session.get(Task, "task-0000")
    assert archived is not None
    archived.title = "夏日 archived"
    session.commit()

    # When: matching tasks are listed by tag without including archives.
    page = list_workstation_tasks(session, TaskListQuery(tag="summer", page=1, page_size=100))

    # Then: archive exclusion and deterministic updated_at/id ordering are preserved.
    assert "task-0000" not in {item.task_id for item in page.items}
    assert {"task-0010", "task-0020"}.issubset({item.task_id for item in page.items})
    tied_ids = [item.task_id for item in page.items if item.task_id in {"task-0010", "task-0020"}]
    assert tied_ids == ["task-0020", "task-0010"]
    assert all("summer" in item.tags for item in page.items)


def test_list_workstation_tasks_escapes_like_wildcards_without_fts(session: Session, monkeypatch) -> None:
    # Given: a literal title that contains SQL LIKE wildcard characters.
    from app.api.schemas.workstation import TaskListQuery
    from app.models import MediaSource, Task
    import app.repositories.workstation as workstation_repository

    session.add_all(
        [
            Task(
                id="task-literal",
                source_url="file:///fixtures/literal.mp4",
                normalized_source_url="file:///fixtures/literal.mp4",
                title="100%_complete",
            ),
            Task(
                id="task-near-match",
                source_url="file:///fixtures/near.mp4",
                normalized_source_url="file:///fixtures/near.mp4",
                title="100AAcomplete",
            ),
        ]
    )
    session.add_all(
        [
            MediaSource(task_id="task-literal", kind="local", locator="file:///fixtures/literal.mp4"),
            MediaSource(task_id="task-near-match", kind="local", locator="file:///fixtures/near.mp4"),
        ]
    )
    session.commit()
    monkeypatch.setattr(workstation_repository, "_sqlite_fts_available", lambda _: False)

    # When: the fallback search receives the wildcard-containing literal.
    page = workstation_repository.list_workstation_tasks(session, TaskListQuery(query="100%_complete"))

    # Then: it matches only the literal title rather than treating % and _ as wildcards.
    assert [item.task_id for item in page.items] == ["task-literal"]


def test_get_task_library_summary_counts_bucketed_tasks_and_storage(session: Session) -> None:
    # Given: a library with each status bucket and archived tasks.
    _seed_library(session)
    from app.models import Task
    from app.repositories.workstation import get_task_library_summary

    tasks = session.exec(select(Task)).all()
    expected = {
        "active": sum(task.status == "running" and task.archived_at is None for task in tasks),
        "queued": sum(task.status == "pending" and task.archived_at is None for task in tasks),
        "review_required": sum(task.status == "success" and task.archived_at is None for task in tasks),
        "failed": sum(task.status == "failed" and task.archived_at is None for task in tasks),
        "archived": sum(task.archived_at is not None for task in tasks),
        "storage_bytes": sum(task.storage_bytes for task in tasks),
    }

    # When: the library summary is requested.
    summary = get_task_library_summary(session)

    # Then: each dashboard bucket is counted in SQL with total storage retained.
    assert summary.model_dump() == expected


def test_get_workstation_task_overview_projects_unstarted_legacy_stages(session: Session) -> None:
    # Given: a pending task that predates PipelineRun creation.
    from app.models import CANONICAL_STAGES, MediaSource, Task, TaskStage
    from app.repositories.workstation import get_workstation_task_overview

    task_id = "task-pending"
    session.add(
        Task(
            id=task_id,
            source_url="file:///fixtures/pending.mp4",
            normalized_source_url="file:///fixtures/pending.mp4",
            status="pending",
            title="Pending source",
        )
    )
    session.add(MediaSource(task_id=task_id, kind="local", locator="file:///fixtures/pending.mp4"))
    session.add_all([TaskStage(task_id=task_id, name=name, status="pending") for name in CANONICAL_STAGES])
    session.commit()

    # When: the workstation overview is requested.
    overview = get_workstation_task_overview(session, task_id)

    # Then: it exposes all seven planned legacy stages without inventing a run ID.
    assert overview is not None
    assert overview.pipeline_run_id is None
    assert [stage.name for stage in overview.stages] == CANONICAL_STAGES
    assert all(stage.planned for stage in overview.stages)
