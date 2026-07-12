"""Server-sent events for durable workstation projections."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from app.services.workstation_events import iter_events

router = APIRouter(prefix="/v2/events", tags=["workstation-events"])


@router.get("")
async def workstation_events_endpoint(
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID", ge=0)] = None,
) -> StreamingResponse:
    """Keep a browser client synchronized through replayable SSE state changes."""
    return StreamingResponse(
        iter_events(last_event_id, heartbeat_seconds=15),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
