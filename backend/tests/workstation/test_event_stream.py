from __future__ import annotations

from collections.abc import AsyncIterator
import json

import anyio
import pytest
from sqlmodel import Session, select


def _reset_runtime_state() -> None:
    from app.db import reset_db_runtime

    reset_db_runtime()


@pytest.fixture()
def database(tmp_path, monkeypatch):
    # Given: an isolated workstation database.
    database_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    _reset_runtime_state()

    from app.db import get_engine, init_db

    init_db()
    return get_engine()


async def _read_frames(stream: AsyncIterator[str], count: int) -> list[str]:
    """Read a bounded set of frames from an otherwise open event stream."""
    frames: list[str] = []
    for _ in range(count):
        frames.append(await anext(stream))
    await stream.aclose()
    return frames


def test_event_stream_replays_monotonic_events_after_last_event_id(database) -> None:
    from app.services.workstation_events import iter_events, publish_event

    # Given: three committed event rows in creation order.
    with Session(database) as session:
        first = publish_event(session, "task.created", "task-a", {"task_id": "task-a", "status": "pending"})
        second = publish_event(session, "task.updated", "task-a", {"task_id": "task-a", "status": "running"})
        third = publish_event(session, "stage.updated", "task-a", {"task_id": "task-a", "stage_name": "ingest"})
        first_id, second_id, third_id = first.id, second.id, third.id
        session.commit()

    # When: a reconnect identifies the second event as its last received frame.
    frames = anyio.run(_read_frames, iter_events(second_id, heartbeat_seconds=15), 1)

    # Then: IDs are monotonic and the reconnect gets only the later frame.
    assert first_id is not None
    assert second_id is not None
    assert third_id is not None
    assert first_id < second_id < third_id
    assert frames == [
        f'id: {third_id}\nevent: stage.updated\ndata: {{"task_id":"task-a","stage_name":"ingest"}}\n\n'
    ]


def test_event_stream_serializes_sse_frame_and_emits_inactivity_heartbeat(database) -> None:
    from app.services.workstation_events import iter_events, publish_event

    # Given: one committed task update event.
    with Session(database) as session:
        event = publish_event(session, "task.updated", "task-a", {"task_id": "task-a", "status": "running"})
        event_id = event.id
        session.commit()

    # When: its event frame is read, followed by a stream with no events.
    frame = anyio.run(_read_frames, iter_events(None, heartbeat_seconds=15), 1)[0]
    heartbeat = anyio.run(_read_frames, iter_events(event_id, heartbeat_seconds=0), 1)[0]

    # Then: clients receive the SSE fields and a standards-compliant comment heartbeat.
    assert event_id is not None
    assert frame == f'id: {event_id}\nevent: task.updated\ndata: {{"task_id":"task-a","status":"running"}}\n\n'
    assert heartbeat == ": heartbeat\n\n"


def test_task_and_queue_mutations_publish_public_event_projections(database, tmp_path, monkeypatch) -> None:
    from app.models import Task, TaskStage, WorkstationEvent
    from app.repositories.tasks import create_task, retry_task_from_stage

    # Given: a failed task with a source URL that must not enter its event payloads.
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "host-private-data"))
    with Session(database) as session:
        created, was_created = create_task(session, "https://www.bilibili.com/video/BV1event001")
        task_id = created["task_id"]
        task = session.get(Task, task_id)
        stage = session.exec(select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")).one()
        assert task is not None
        task.status = "failed"
        stage.status = "failed"
        session.add(task)
        session.add(stage)
        session.commit()

        # When: the retry returns the task to its public pending projection.
        retry_task_from_stage(session, task_id, "asr")
        events = session.exec(select(WorkstationEvent).order_by(WorkstationEvent.id)).all()

    # Then: task, stage, and queue messages are durable public-safe state transitions.
    assert was_created is True
    assert {event.event_type for event in events} >= {"task.created", "task.updated", "queue.updated", "stage.updated"}
    assert all(str(tmp_path) not in event.payload_json for event in events)


def test_artifact_persistence_publishes_public_ready_event(database) -> None:
    from app.models import Task, WorkstationEvent
    from app.services.storage import get_task_root, persist_artifact_metadata

    # Given: a staged task and a managed artifact file.
    task_id = "task-artifact"
    artifact_path = get_task_root(task_id) / "work" / "transcript.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("{}", encoding="utf-8")
    with Session(database) as session:
        session.add(
            Task(
                id=task_id,
                source_url="https://www.bilibili.com/video/BV1artifact001",
                normalized_source_url="https://www.bilibili.com/video/BV1artifact001",
            )
        )

        # When: the artifact metadata is persisted in the task transaction.
        artifact = persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="asr",
            kind="transcript_json",
            path=artifact_path,
        )
        event = session.exec(select(WorkstationEvent).where(WorkstationEvent.event_type == "artifact.ready")).one()

    # Then: the ready event refers only to the public content route, never its host path.
    assert artifact.id is not None
    assert event.payload_json == (
        f'{{"task_id":"{task_id}","artifact_id":{artifact.id},'
        '"stage_name":"asr","kind":"transcript_json",'
        f'"path":"/api/tasks/{task_id}/artifacts/{artifact.id}/content/transcript.json"}}'
    )
    assert str(artifact_path) not in event.payload_json


def test_events_endpoint_declares_sse_response() -> None:
    from app.api.routes.workstation_events import workstation_events_endpoint

    # Given: the v2 event endpoint.
    # When: FastAPI constructs its response.
    response = anyio.run(workstation_events_endpoint, None)

    # Then: clients receive the event-stream contract without buffering caches.
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


def test_v2_task_creation_stages_a_public_created_event(database) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import WorkstationEvent

    # Given: a valid v2 Bilibili creation request.
    payload = {
        "source": {"kind": "bilibili", "url": "https://www.bilibili.com/video/BV1eventv2001"},
        "profile_id": "standard",
        "priority": 7,
    }

    # When: the v2 creation route commits its task transaction.
    with TestClient(app) as client:
        response = client.post("/api/v2/tasks", json=payload)
    task_id = response.json()["task_id"]

    # Then: SSE consumers receive only the new task's public lifecycle projection.
    with Session(database) as session:
        event = session.exec(select(WorkstationEvent).where(WorkstationEvent.event_type == "task.created")).one()
        queue_events = session.exec(
            select(WorkstationEvent).where(WorkstationEvent.event_type == "queue.updated")
        ).all()
    assert response.status_code == 201
    assert json.loads(event.payload_json) == {"task_id": task_id, "status": "pending"}
    assert len(queue_events) == 1
    assert json.loads(queue_events[0].payload_json) == {
        "revision": 2,
        "active": None,
        "queued": [{"task_id": task_id, "position": 1, "priority": 7, "state": "queued"}],
        "paused": [],
    }


def test_runner_cancellation_commits_public_task_and_stage_events(database) -> None:
    from app.models import Task, TaskJob, TaskStage, WorkstationEvent
    from app.repositories.tasks import create_task
    from app.services.task_control import activate_execution, request_cancel
    import app.services.task_runner as task_runner

    # Given: a worker-claimed stage with a requested cancellation before the runner starts it.
    with Session(database) as session:
        created, was_created = create_task(session, "https://www.bilibili.com/video/BV1eventcancel001")
        task_id = created["task_id"]
        task = session.get(Task, task_id)
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        assert task is not None
        task.status = "running"
        job.status = "running"
        stage.status = "running"
        session.add(task)
        session.add(job)
        session.add(stage)
        session.commit()
        activate_execution(session, task_id=task_id, execution_token="token-event-cancel")
        request_cancel(session, task_id=task_id)

    # When: the runner finalizes that cancellation before the next stage checkpoint.
    with Session(database) as session:
        result = task_runner.run_task_pipeline(
            session,
            task_id,
            claimed_stage_running=True,
            execution_token="token-event-cancel",
        )

    # Then: the committed cancellation projection includes both affected public entities.
    with Session(database) as session:
        events = session.exec(select(WorkstationEvent).order_by(WorkstationEvent.id)).all()
    payloads_by_type = [(event.event_type, json.loads(event.payload_json)) for event in events]
    assert was_created is True
    assert result.final_status == "cancelled"
    assert ("task.updated", {"task_id": task_id, "status": "cancelled"}) in payloads_by_type
    assert (
        "stage.updated",
        {
            "task_id": task_id,
            "stage_name": "ingest",
            "status": "cancelled",
            "failure_code": None,
            "attempts": 0,
        },
    ) in payloads_by_type


def test_task_runner_stages_public_task_and_stage_events_at_stage_checkpoints(database, monkeypatch) -> None:
    from app.models import WorkstationEvent
    from app.repositories.tasks import create_task
    import app.services.task_runner as task_runner

    # Given: a pending task whose stage executors complete without external dependencies.
    with Session(database) as session:
        created, was_created = create_task(session, "https://www.bilibili.com/video/BV1eventrunner001")
        task_id = created["task_id"]
        session.commit()
    assert was_created is True
    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: lambda _session, _task_id: None for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    # When: the normal runner commits each stage checkpoint.
    with Session(database) as session:
        task_runner.run_task_pipeline(session, task_id)

    # Then: every completed stage and the terminal task state are replayable public events.
    with Session(database) as session:
        events = session.exec(select(WorkstationEvent).order_by(WorkstationEvent.id)).all()
    payloads_by_type = [(event.event_type, json.loads(event.payload_json)) for event in events]
    assert ("task.updated", {"task_id": task_id, "status": "success"}) in payloads_by_type
    for stage_name in task_runner.CANONICAL_STAGE_ORDER:
        assert any(
            event_type == "stage.updated"
            and payload["task_id"] == task_id
            and payload["stage_name"] == stage_name
            and payload["status"] == "success"
            for event_type, payload in payloads_by_type
        )


def test_worker_claim_and_completion_stage_public_task_and_stage_events(database) -> None:
    from app.models import WorkstationEvent
    from app.repositories.tasks import create_task
    from app.worker import claim_next_job, complete_job

    # Given: one pending queue entry.
    with Session(database) as session:
        created, was_created = create_task(session, "https://www.bilibili.com/video/BV1eventworker001")
        task_id = created["task_id"]
        session.commit()
    assert was_created is True

    # When: the worker claims and then completes that task directly.
    claimed = claim_next_job()
    assert claimed is not None
    complete_job(task_id, success=True)

    # Then: both direct transitions have public task and stage projections.
    with Session(database) as session:
        events = session.exec(select(WorkstationEvent).order_by(WorkstationEvent.id)).all()
    payloads_by_type = [(event.event_type, json.loads(event.payload_json)) for event in events]
    assert ("task.updated", {"task_id": task_id, "status": "running"}) in payloads_by_type
    assert ("task.updated", {"task_id": task_id, "status": "success"}) in payloads_by_type
    assert any(
        event_type == "stage.updated"
        and payload["task_id"] == task_id
        and payload["status"] == "running"
        for event_type, payload in payloads_by_type
    )
    assert any(
        event_type == "stage.updated"
        and payload["task_id"] == task_id
        and payload["status"] == "success"
        for event_type, payload in payloads_by_type
    )


def test_event_replay_reads_bounded_ordered_pages(database, monkeypatch) -> None:
    from sqlalchemy import event as sqlalchemy_event

    from app.services import workstation_events
    from app.services.workstation_events import iter_events, publish_event

    # Given: more committed events than one configured replay page.
    monkeypatch.setattr(workstation_events, "_EVENT_PAGE_SIZE", 2)
    with Session(database) as session:
        for index in range(5):
            publish_event(
                session,
                "task.updated",
                f"task-{index}",
                {"task_id": f"task-{index}", "status": "running"},
            )
        session.commit()

    # When: a client consumes the complete replay.
    replay_queries: list[str] = []

    def record_query(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        if "FROM workstationevent" in statement:
            replay_queries.append(statement)

    sqlalchemy_event.listen(database, "before_cursor_execute", record_query)
    try:
        frames = anyio.run(_read_frames, iter_events(None, heartbeat_seconds=15), 5)
    finally:
        sqlalchemy_event.remove(database, "before_cursor_execute", record_query)

    # Then: the stream drains ordered pages without duplicates or an unbounded first query.
    ids = [int(frame.splitlines()[0].removeprefix("id: ")) for frame in frames]
    assert ids == sorted(ids)
    assert len(set(ids)) == 5
    assert len(replay_queries) == 3
    assert all("LIMIT" in statement for statement in replay_queries)
