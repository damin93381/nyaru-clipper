"""Revisioned workstation queue operations backed by SQLite transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlmodel import Session, select

from app.models import QueueEntry, QueueState, utc_now


QueueMutationState = Literal["queued", "paused"]


@dataclass(frozen=True, slots=True)
class QueueItem:
    """A queue entry safe to expose through the workstation scheduling API."""

    task_id: str
    position: int
    priority: int
    state: str


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    """The complete optimistic-concurrency view of the workstation queue."""

    revision: int
    active: QueueItem | None
    queued: list[QueueItem]
    paused: list[QueueItem]


@dataclass(frozen=True, slots=True)
class QueueConflict(Exception):
    """A mutation rejected because its queue view was no longer authoritative."""

    current_snapshot: QueueSnapshot
    reason: str

    def __str__(self) -> str:
        return self.reason


def get_queue_snapshot(session: Session) -> QueueSnapshot:
    """Return the queue projection in the same order used by scheduler clients."""
    state = _queue_state(session)
    entries = session.exec(select(QueueEntry)).all()
    active_entries = sorted(
        (entry for entry in entries if entry.state == "running"),
        key=lambda entry: (entry.created_at, entry.task_id),
    )
    active = _item(active_entries[0]) if active_entries else None
    queued = [_item(entry) for entry in _ordered(entries, "queued")]
    paused = [_item(entry) for entry in _ordered(entries, "paused")]
    return QueueSnapshot(revision=state.revision, active=active, queued=queued, paused=paused)


def reorder_queue(session: Session, ordered_task_ids: list[str], expected_revision: int) -> QueueSnapshot:
    """Replace queued ordering if the caller's revision and task set are current."""
    _begin_immediate(session)
    snapshot = get_queue_snapshot(session)
    if snapshot.revision != expected_revision:
        raise QueueConflict(snapshot, "Queue revision is stale")
    if len(set(ordered_task_ids)) != len(ordered_task_ids):
        raise QueueConflict(snapshot, "Queue order contains duplicate task IDs")

    queued_ids = [item.task_id for item in snapshot.queued]
    if set(ordered_task_ids) != set(queued_ids):
        active_ids = {snapshot.active.task_id} if snapshot.active is not None else set()
        if active_ids.intersection(ordered_task_ids) or active_ids and set(ordered_task_ids) != set(queued_ids):
            raise QueueConflict(snapshot, "Active task cannot be moved")
        raise QueueConflict(snapshot, "Queue order must contain every queued task exactly once")

    by_task_id = {entry.task_id: entry for entry in session.exec(select(QueueEntry)).all()}
    now = utc_now()
    for position, task_id in enumerate(ordered_task_ids, start=1):
        entry = by_task_id[task_id]
        entry.position = position
        entry.updated_at = now
        session.add(entry)
    _normalize_positions(session, now=now)
    return _increment_and_snapshot(session, now=now)


def set_queue_state(session: Session, task_id: str, state: QueueMutationState) -> QueueSnapshot:
    """Pause or resume one waiting queue entry and publish a new revision."""
    _begin_immediate(session)
    entry = session.get(QueueEntry, task_id)
    if entry is None:
        raise KeyError(task_id)
    if entry.state not in {"queued", "paused"}:
        raise QueueConflict(get_queue_snapshot(session), "Active or finished task cannot be moved")
    now = utc_now()
    entry.state = state
    entry.updated_at = now
    session.add(entry)
    _normalize_positions(session, now=now)
    return _increment_and_snapshot(session, now=now)


def enqueue_task(session: Session, task_id: str) -> QueueEntry:
    """Ensure a task has a queued projection entry before the worker can see it."""
    entry = session.get(QueueEntry, task_id)
    if entry is not None:
        return entry
    now = utc_now()
    position = len(session.exec(select(QueueEntry).where(QueueEntry.state.in_(["queued", "paused"]))).all()) + 1
    entry = QueueEntry(task_id=task_id, position=position, state="queued", created_at=now, updated_at=now)
    session.add(entry)
    queue_state = _queue_state(session)
    queue_state.revision += 1
    queue_state.updated_at = now
    session.add(queue_state)
    _normalize_positions(session, now=now)
    return entry


def requeue_task(session: Session, task_id: str) -> QueueEntry:
    """Put a retried task at the back of the waiting queue as one new revision."""
    entry = session.get(QueueEntry, task_id)
    if entry is None:
        return enqueue_task(session, task_id)
    if entry.state == "running":
        raise QueueConflict(get_queue_snapshot(session), "Active task cannot be requeued")
    now = utc_now()
    entry.state = "queued"
    entry.position = len(session.exec(select(QueueEntry).where(QueueEntry.state.in_(["queued", "paused"]))).all()) + 1
    entry.updated_at = now
    session.add(entry)
    _normalize_positions(session, now=now)
    _increment_and_snapshot(session, now=now)
    return entry


def claim_next_queue_entry(session: Session) -> QueueEntry | None:
    """Atomically claim the sole GPU queue entry according to priority and position."""
    _begin_immediate(session)
    running = session.exec(select(QueueEntry).where(QueueEntry.state == "running")).first()
    if running is not None:
        return None
    entry = session.exec(
        select(QueueEntry)
        .where(QueueEntry.state == "queued")
        .order_by(QueueEntry.priority.desc(), QueueEntry.position.asc(), QueueEntry.created_at.asc())
    ).first()
    if entry is None:
        return None
    now = utc_now()
    entry.state = "running"
    entry.updated_at = now
    session.add(entry)
    _normalize_positions(session, now=now)
    _increment_and_snapshot(session, now=now)
    return entry


def finish_queue_entry(session: Session, task_id: str) -> None:
    """Retain a completed queue row as immutable history rather than deleting it."""
    entry = session.get(QueueEntry, task_id)
    if entry is None:
        return
    if entry.state == "finished":
        return
    entry.state = "finished"
    entry.updated_at = utc_now()
    session.add(entry)
    _normalize_positions(session, now=entry.updated_at)
    _increment_and_snapshot(session, now=entry.updated_at)


def _begin_immediate(session: Session) -> None:
    """Acquire SQLite's writer lock before reading mutable queue state."""
    if session.in_transaction():
        return
    session.execute(text("BEGIN IMMEDIATE"))


def _queue_state(session: Session) -> QueueState:
    state = session.get(QueueState, 1)
    if state is None:
        state = QueueState()
        session.add(state)
        session.flush()
    return state


def _ordered(entries: list[QueueEntry], state: str) -> list[QueueEntry]:
    return sorted(
        (entry for entry in entries if entry.state == state),
        key=lambda entry: (-entry.priority, entry.position, entry.created_at, entry.task_id),
    )


def _item(entry: QueueEntry) -> QueueItem:
    return QueueItem(task_id=entry.task_id, position=entry.position, priority=entry.priority, state=entry.state)


def _normalize_positions(session: Session, *, now) -> None:
    entries = session.exec(select(QueueEntry)).all()
    ordered = [
        *sorted((entry for entry in entries if entry.state == "running"), key=lambda entry: (entry.created_at, entry.task_id)),
        *_ordered(entries, "queued"),
        *_ordered(entries, "paused"),
        *sorted((entry for entry in entries if entry.state == "finished"), key=lambda entry: (entry.created_at, entry.task_id)),
    ]
    for position, entry in enumerate(ordered, start=1):
        if entry.position != position:
            entry.position = position
            entry.updated_at = now
            session.add(entry)


def _increment_and_snapshot(session: Session, *, now) -> QueueSnapshot:
    state = _queue_state(session)
    state.revision += 1
    state.updated_at = now
    session.add(state)
    session.flush()
    return get_queue_snapshot(session)
