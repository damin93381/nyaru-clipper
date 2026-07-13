"""Versioned manual queue API with optimistic concurrency snapshots."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ConfigDict, Field
from sqlmodel import Session

from app.api.schemas.workstation import WorkstationSchema
from app.db import get_session
from app.services.workstation_queue import (
    QueueConflict,
    QueueItem,
    QueueSnapshot,
    get_queue_snapshot,
    reorder_queue,
    set_queue_state,
)


router = APIRouter(prefix="/v2/queue", tags=["workstation-queue"])


class QueueItemResponse(WorkstationSchema):
    """Public queue entry fields."""

    task_id: str
    position: int
    priority: int
    state: str


class QueueSnapshotResponse(WorkstationSchema):
    """Revisioned queue document used for optimistic updates."""

    revision: int
    active: QueueItemResponse | None
    queued: list[QueueItemResponse]
    paused: list[QueueItemResponse]


class QueueOrderRequest(WorkstationSchema):
    """A complete replacement ordering for all currently queued task IDs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ordered_task_ids: list[str] = Field(min_length=0)
    expected_revision: int = Field(ge=1)


class QueueStateRequest(WorkstationSchema):
    """The supported manual queue states."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: Literal["queued", "paused"]


@router.get("", response_model=QueueSnapshotResponse)
def get_queue_endpoint(session: Session = Depends(get_session)) -> QueueSnapshotResponse:
    """Read the current manual scheduling queue."""
    return _snapshot_response(get_queue_snapshot(session))


@router.put(
    "/order",
    response_model=QueueSnapshotResponse,
    responses={
        409: {
            "description": "The supplied queue revision is stale; the response body is the authoritative snapshot.",
            "model": QueueSnapshotResponse,
        }
    },
)
def reorder_queue_endpoint(
    payload: QueueOrderRequest,
    session: Session = Depends(get_session),
) -> QueueSnapshotResponse | JSONResponse:
    """Replace the queued ordering if the supplied revision is still current."""
    try:
        snapshot = reorder_queue(session, list(payload.ordered_task_ids), payload.expected_revision)
    except QueueConflict as conflict:
        session.rollback()
        return JSONResponse(status_code=409, content=_snapshot_response(conflict.current_snapshot).model_dump(mode="json"))
    session.commit()
    return _snapshot_response(snapshot)


@router.patch("/{task_id}", response_model=QueueSnapshotResponse)
def set_queue_state_endpoint(
    task_id: str,
    payload: QueueStateRequest,
    session: Session = Depends(get_session),
) -> QueueSnapshotResponse:
    """Pause or resume a waiting task."""
    try:
        snapshot = set_queue_state(session, task_id, payload.state)
    except KeyError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except QueueConflict as conflict:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(conflict)) from conflict
    session.commit()
    return _snapshot_response(snapshot)


def _snapshot_response(snapshot: QueueSnapshot) -> QueueSnapshotResponse:
    return QueueSnapshotResponse(
        revision=snapshot.revision,
        active=_item_response(snapshot.active),
        queued=[_item_response(item) for item in snapshot.queued],
        paused=[_item_response(item) for item in snapshot.paused],
    )


def _item_response(item: QueueItem | None) -> QueueItemResponse | None:
    if item is None:
        return None
    return QueueItemResponse(task_id=item.task_id, position=item.position, priority=item.priority, state=item.state)
