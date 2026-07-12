from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select


def _reset_runtime_state() -> None:
    from app.db import reset_db_runtime

    reset_db_runtime()


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    # Given: an isolated, migrated workstation database.
    database_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    _reset_runtime_state()

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _seed_task(session: Session, *, task_id: str, status: str = "pending") -> None:
    from app.models import MediaSource, Task

    session.add(
        Task(
            id=task_id,
            source_url=f"file:///fixtures/{task_id}.mp4",
            normalized_source_url=f"file:///fixtures/{task_id}.mp4",
            status=status,
            title=f"Library {task_id}",
        )
    )
    session.add(MediaSource(task_id=task_id, kind="local", locator=f"file:///fixtures/{task_id}.mp4"))


def test_task_library_list_parses_filters_and_clamps_page_size(client: TestClient) -> None:
    # Given: more tasks than the public page-size limit, including a tagged running task.
    from app.db import session_scope
    from app.models import TaskTag, TaskTagLink

    with session_scope() as session:
        session.add(TaskTag(name="summer"))
        for index in range(101):
            task_id = f"task-{index:03d}"
            _seed_task(session, task_id=task_id, status="running" if index == 0 else "pending")
        session.add(TaskTagLink(task_id="task-000", tag_name="summer"))

    # When: the library receives query-string filters and an oversized page.
    response = client.get(
        "/api/v2/tasks",
        params={"statuses": "running", "tag": "summer", "page_size": 500},
    )

    # Then: parsed filters are applied and the public page is capped at 100 records.
    assert response.status_code == 200
    assert response.json()["page_size"] == 100
    assert response.json()["total"] == 1
    assert [item["task_id"] for item in response.json()["items"]] == ["task-000"]


def test_task_library_summary_and_missing_overview_are_exposed(client: TestClient) -> None:
    # Given: a library with one queued task.
    from app.db import session_scope

    with session_scope() as session:
        _seed_task(session, task_id="task-summary")

    # When: the dashboard summary and a missing overview are requested.
    summary_response = client.get("/api/v2/tasks/summary")
    missing_response = client.get("/api/v2/tasks/task-missing")

    # Then: the summary has the queued task and the absent task uses the v1-compatible 404 detail.
    assert summary_response.status_code == 200
    assert summary_response.json()["queued"] == 1
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "Task not found"}


def test_task_library_patch_replaces_tags(client: TestClient) -> None:
    # Given: one task with a stale tag.
    from app.db import session_scope
    from app.models import TaskTag, TaskTagLink

    with session_scope() as session:
        _seed_task(session, task_id="task-tags")
        session.add_all([TaskTag(name="old"), TaskTag(name="new"), TaskTag(name="featured")])
        session.add(TaskTagLink(task_id="task-tags", tag_name="old"))

    # When: the task metadata replaces its tags.
    response = client.patch("/api/v2/tasks/task-tags", json={"tags": ["featured", "new"]})

    # Then: the replacement is persisted in deterministic order.
    assert response.status_code == 200
    assert response.json()["tags"] == ["featured", "new"]


def test_task_library_bulk_reports_per_task_archive_and_missing_results(client: TestClient) -> None:
    # Given: one existing task and one absent task identifier.
    from app.db import session_scope

    with session_scope() as session:
        _seed_task(session, task_id="task-a")

    # When: both are archived in one bulk request.
    response = client.post(
        "/api/v2/tasks/bulk",
        json={"operation": "archive", "task_ids": ["task-a", "task-missing"]},
    )

    # Then: the operation commits the existing task and reports the missing item without failing the batch.
    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {"task_id": "task-a", "status": "success", "message": None},
            {"task_id": "task-missing", "status": "not_found", "message": "Task not found"},
        ]
    }


def test_task_library_bulk_unarchives_and_rejects_active_deletion(client: TestClient) -> None:
    # Given: an archived task and a currently running task.
    from app.db import session_scope

    with session_scope() as session:
        _seed_task(session, task_id="task-archived")
        _seed_task(session, task_id="task-running", status="running")

    client.post("/api/v2/tasks/bulk", json={"operation": "archive", "task_ids": ["task-archived"]})

    # When: the archived task is restored and the active task is deleted.
    unarchive_response = client.post(
        "/api/v2/tasks/bulk",
        json={"operation": "unarchive", "task_ids": ["task-archived"]},
    )
    delete_response = client.post(
        "/api/v2/tasks/bulk",
        json={"operation": "delete", "task_ids": ["task-running"]},
    )

    # Then: restore succeeds while active work is protected from deletion.
    assert unarchive_response.status_code == 200
    assert unarchive_response.json()["results"] == [
        {"task_id": "task-archived", "status": "success", "message": None}
    ]
    assert client.get("/api/v2/tasks/task-archived").json()["archived_at"] is None
    assert delete_response.status_code == 200
    assert delete_response.json()["results"] == [
        {"task_id": "task-running", "status": "rejected", "message": "Task is actively running"}
    ]


def test_task_library_bulk_delete_removes_all_task_owned_database_rows(client: TestClient) -> None:
    # Given: an inactive task with every direct and pipeline-owned database record, plus a running task.
    from app.db import session_scope
    from app.models import (
        Artifact,
        ClipCandidate,
        MediaSource,
        PipelineRun,
        QueueEntry,
        StageRun,
        Task,
        TaskExecutionControl,
        TaskExecutionProgress,
        TaskJob,
        TaskStage,
        TaskTag,
        TaskTagLink,
    )

    deleted_task_id = "task-delete"
    deleted_run_id = "run-delete"
    with session_scope() as session:
        _seed_task(session, task_id=deleted_task_id, status="success")
        _seed_task(session, task_id="task-running", status="running")
        session.add(TaskTag(name="delete-tag"))
        session.add_all(
            [
                TaskJob(task_id=deleted_task_id, stage_name="asr"),
                TaskStage(task_id=deleted_task_id, name="asr"),
                Artifact(task_id=deleted_task_id, stage_name="asr", kind="transcript_json", path="work/asr.json"),
                ClipCandidate(task_id=deleted_task_id, start_seconds=1.0, end_seconds=2.0, score=0.9, reason="fixture"),
                TaskExecutionProgress(
                    task_id=deleted_task_id,
                    stage_name="asr",
                    current_phase="persist",
                    phase_index=1,
                    phase_count=1,
                ),
                TaskExecutionControl(task_id=deleted_task_id),
                TaskTagLink(task_id=deleted_task_id, tag_name="delete-tag"),
                QueueEntry(task_id=deleted_task_id, position=1),
                PipelineRun(id=deleted_run_id, task_id=deleted_task_id, status="success"),
                StageRun(run_id=deleted_run_id, name="asr", status="success"),
            ]
        )

    # When: the inactive task, a missing task, and an active task are deleted together.
    response = client.post(
        "/api/v2/tasks/bulk",
        json={"operation": "delete", "task_ids": [deleted_task_id, "task-missing", "task-running"]},
    )

    # Then: each result stays independent and no database rows remain for the deleted task.
    assert response.status_code == 200
    assert response.json()["results"] == [
        {"task_id": deleted_task_id, "status": "success", "message": None},
        {"task_id": "task-missing", "status": "not_found", "message": "Task not found"},
        {"task_id": "task-running", "status": "rejected", "message": "Task is actively running"},
    ]

    with session_scope() as session:
        assert session.get(Task, deleted_task_id) is None
        assert session.get(TaskExecutionProgress, deleted_task_id) is None
        assert session.get(TaskExecutionControl, deleted_task_id) is None
        assert session.exec(select(TaskJob).where(TaskJob.task_id == deleted_task_id)).all() == []
        assert session.exec(select(TaskStage).where(TaskStage.task_id == deleted_task_id)).all() == []
        assert session.exec(select(Artifact).where(Artifact.task_id == deleted_task_id)).all() == []
        assert session.exec(select(ClipCandidate).where(ClipCandidate.task_id == deleted_task_id)).all() == []
        assert session.exec(select(MediaSource).where(MediaSource.task_id == deleted_task_id)).all() == []
        assert session.exec(select(TaskTagLink).where(TaskTagLink.task_id == deleted_task_id)).all() == []
        assert session.exec(select(QueueEntry).where(QueueEntry.task_id == deleted_task_id)).all() == []
        assert session.exec(select(PipelineRun).where(PipelineRun.task_id == deleted_task_id)).all() == []
        assert session.exec(select(StageRun).where(StageRun.run_id == deleted_run_id)).all() == []
