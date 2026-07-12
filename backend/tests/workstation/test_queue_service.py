from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlmodel import Session, select


def _reset_runtime_state() -> None:
    from app.db import reset_db_runtime

    reset_db_runtime()


@pytest.fixture()
def database(tmp_path, monkeypatch):
    database_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    _reset_runtime_state()

    from app.db import get_engine, init_db

    init_db()
    return get_engine()


def _seed_queue(session: Session, task_ids: tuple[str, ...]) -> None:
    from app.models import QueueEntry, QueueState, Task, TaskJob, TaskStage

    queue_state = session.get(QueueState, 1)
    assert queue_state is not None
    queue_state.revision = 4
    session.add(queue_state)
    for position, task_id in enumerate(task_ids, start=1):
        session.add(
            Task(
                id=task_id,
                source_url=f"file:///fixtures/{task_id}.mp4",
                normalized_source_url=f"file:///fixtures/{task_id}.mp4",
            )
        )
        session.add(QueueEntry(task_id=task_id, position=position, state="queued"))
        session.add(TaskJob(task_id=task_id, stage_name="ingest", status="pending"))
        session.add(TaskStage(task_id=task_id, name="ingest", status="pending"))
    session.commit()


def test_reorder_queue_replaces_queued_order_and_increments_revision(database) -> None:
    from app.services.workstation_queue import reorder_queue

    with Session(database) as session:
        _seed_queue(session, ("task-a", "task-b", "task-c"))
        snapshot = reorder_queue(session, ["task-c", "task-a", "task-b"], expected_revision=4)
        session.commit()

    assert [item.task_id for item in snapshot.queued] == ["task-c", "task-a", "task-b"]
    assert snapshot.revision == 5


@pytest.mark.parametrize(
    ("ordered_task_ids", "expected_message"),
    [
        (["task-a", "task-a", "task-c"], "duplicate"),
        (["task-a", "task-c"], "queued"),
    ],
)
def test_reorder_queue_rejects_non_bijective_queued_order(database, ordered_task_ids, expected_message: str) -> None:
    from app.services.workstation_queue import QueueConflict, reorder_queue

    with Session(database) as session:
        _seed_queue(session, ("task-a", "task-b", "task-c"))
        with pytest.raises(QueueConflict, match=expected_message):
            reorder_queue(session, ordered_task_ids, expected_revision=4)


def test_reorder_queue_rejects_active_task_moves_and_stale_revision(database) -> None:
    from app.models import QueueEntry
    from app.services.workstation_queue import QueueConflict, reorder_queue

    with Session(database) as session:
        _seed_queue(session, ("task-a", "task-b", "task-c"))
        active = session.get(QueueEntry, "task-a")
        assert active is not None
        active.state = "running"
        session.add(active)
        session.commit()

        with pytest.raises(QueueConflict, match="Active"):
            reorder_queue(session, ["task-a", "task-b", "task-c"], expected_revision=4)

        with pytest.raises(QueueConflict) as exc_info:
            reorder_queue(session, ["task-b", "task-c"], expected_revision=3)

    assert exc_info.value.current_snapshot.revision == 4
    assert exc_info.value.current_snapshot.active is not None
    assert exc_info.value.current_snapshot.active.task_id == "task-a"


def test_paused_entry_cannot_be_claimed(database) -> None:
    from app.services.workstation_queue import claim_next_queue_entry, set_queue_state

    with Session(database) as session:
        _seed_queue(session, ("task-a", "task-b"))
        set_queue_state(session, "task-a", "paused")
        claimed = claim_next_queue_entry(session)
        claimed_task_id = claimed.task_id if claimed is not None else None
        session.commit()

    assert claimed_task_id == "task-b"


def test_concurrent_claims_leave_one_running_gpu_entry(database) -> None:
    from app.models import QueueEntry
    from app.services.workstation_queue import claim_next_queue_entry

    with Session(database) as session:
        _seed_queue(session, ("task-a", "task-b"))

    def claim_one() -> str | None:
        with Session(database) as session:
            claimed = claim_next_queue_entry(session)
            session.commit()
            return claimed.task_id if claimed is not None else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed_ids = list(executor.map(lambda _: claim_one(), range(2)))

    with Session(database) as session:
        running_entries = session.exec(select(QueueEntry).where(QueueEntry.state == "running")).all()

    assert [task_id for task_id in claimed_ids if task_id is not None] in (["task-a"], ["task-b"])
    assert len(running_entries) == 1
