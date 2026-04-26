from __future__ import annotations

from fastapi import APIRouter

from app.db import get_engine
from app.services.runtime_capabilities import get_runtime_capability_summary
from app.services.storage import get_tasks_root

router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck() -> dict[str, object]:
    get_engine()
    get_tasks_root()
    return {
        "status": "ok",
        "storage": "ok",
        "database": "ok",
        "runtime_capabilities": get_runtime_capability_summary(),
    }
