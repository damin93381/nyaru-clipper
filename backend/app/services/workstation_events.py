"""Durable, replayable workstation events for the v2 SSE API."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import anyio
from sqlalchemy import delete
from sqlmodel import Session, select

from app.db import get_engine
from app.models import Task, TaskStage, WorkstationEvent, utc_now

_POLL_INTERVAL_SECONDS = 0.5
_EVENT_PAGE_SIZE = 100
_EVENT_RETENTION = timedelta(days=7)
_EVENT_RETENTION_COUNT = 10_000


def publish_event(
    session: Session,
    event_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> WorkstationEvent:
    """Add one event to the caller's transaction after its state mutation is staged."""
    event = WorkstationEvent(
        event_type=event_type,
        entity_id=entity_id,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    session.add(event)
    session.flush()
    _prune_expired_events(session)
    return event


def publish_task_updated(session: Session, task: Task) -> WorkstationEvent:
    """Stage the public task lifecycle projection with its task mutation."""
    return publish_event(
        session,
        "task.updated",
        task.id,
        {"task_id": task.id, "status": task.status},
    )


def publish_stage_updated(session: Session, stage: TaskStage) -> WorkstationEvent:
    """Stage the public stage lifecycle projection with its stage mutation."""
    return publish_event(
        session,
        "stage.updated",
        stage.task_id,
        {
            "task_id": stage.task_id,
            "stage_name": stage.name,
            "status": stage.status,
            "failure_code": stage.failure_code,
            "attempts": stage.attempts,
        },
    )


async def iter_events(last_event_id: int | None, heartbeat_seconds: float) -> AsyncIterator[str]:
    """Replay committed events, then poll with short-lived sessions until disconnected."""
    cursor = last_event_id or 0
    last_activity = time.monotonic()

    while True:
        with Session(get_engine()) as session:
            events = session.exec(
                select(WorkstationEvent)
                .where(WorkstationEvent.id > cursor)
                .order_by(WorkstationEvent.id)
                .limit(_EVENT_PAGE_SIZE)
            ).all()
            frames = [
                (event.id, _serialize_event_frame(event))
                for event in events
                if event.id is not None
            ]

        if frames:
            for event_id, frame in frames:
                cursor = event_id
                last_activity = time.monotonic()
                yield frame
            continue

        if time.monotonic() - last_activity >= heartbeat_seconds:
            last_activity = time.monotonic()
            yield ": heartbeat\n\n"
            continue

        await anyio.sleep(_POLL_INTERVAL_SECONDS)


def _serialize_event_frame(event: WorkstationEvent) -> str:
    """Serialize one persisted public projection as a complete SSE message."""
    if event.id is None:
        raise ValueError("Persisted workstation event is missing its ID")
    return f"id: {event.id}\nevent: {event.event_type}\ndata: {event.payload_json}\n\n"


def _prune_expired_events(session: Session) -> None:
    """Drop expired rows only when doing so preserves the newest event window."""
    retention_boundary = session.exec(
        select(WorkstationEvent.id).order_by(WorkstationEvent.id.desc()).offset(_EVENT_RETENTION_COUNT - 1).limit(1)
    ).first()
    if retention_boundary is None:
        return
    session.exec(
        delete(WorkstationEvent).where(
            WorkstationEvent.created_at < utc_now() - _EVENT_RETENTION,
            WorkstationEvent.id < retention_boundary,
        )
    )
