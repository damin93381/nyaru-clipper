from __future__ import annotations

from fastapi import APIRouter

from app.db import get_engine
from app.services.storage import get_tasks_root

router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck() -> dict[str, str]:
    get_engine()
    get_tasks_root()
    return {"status": "ok", "storage": "ok", "database": "ok"}
