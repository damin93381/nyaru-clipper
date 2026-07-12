from __future__ import annotations

from fastapi.testclient import TestClient
import pytest


def _reset_runtime_state() -> None:
    from app.db import reset_db_runtime

    reset_db_runtime()


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    database_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    _reset_runtime_state()

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _seed_queue() -> None:
    from sqlmodel import Session

    from app.db import get_engine
    from app.models import QueueEntry, QueueState, Task

    with Session(get_engine()) as session:
        queue_state = session.get(QueueState, 1)
        assert queue_state is not None
        queue_state.revision = 4
        session.add(queue_state)
        for position, task_id in enumerate(("task-a", "task-b", "task-c"), start=1):
            session.add(
                Task(
                    id=task_id,
                    source_url=f"file:///fixtures/{task_id}.mp4",
                    normalized_source_url=f"file:///fixtures/{task_id}.mp4",
                )
            )
            session.add(QueueEntry(task_id=task_id, position=position, state="queued"))
        session.commit()


def test_queue_api_reads_reorders_and_returns_authoritative_stale_snapshot(client: TestClient) -> None:
    _seed_queue()

    initial = client.get("/api/v2/queue")
    reordered = client.put(
        "/api/v2/queue/order",
        json={"ordered_task_ids": ["task-c", "task-a", "task-b"], "expected_revision": 4},
    )
    stale = client.put(
        "/api/v2/queue/order",
        json={"ordered_task_ids": ["task-a", "task-b", "task-c"], "expected_revision": 4},
    )

    assert initial.status_code == 200
    assert initial.json()["revision"] == 4
    assert [item["task_id"] for item in reordered.json()["queued"]] == ["task-c", "task-a", "task-b"]
    assert reordered.json()["revision"] == 5
    assert stale.status_code == 409
    assert stale.json() == reordered.json()


def test_queue_api_pauses_a_queued_task(client: TestClient) -> None:
    _seed_queue()

    response = client.patch("/api/v2/queue/task-b", json={"state": "paused"})

    assert response.status_code == 200
    assert [item["task_id"] for item in response.json()["queued"]] == ["task-a", "task-c"]
    assert [item["task_id"] for item in response.json()["paused"]] == ["task-b"]
