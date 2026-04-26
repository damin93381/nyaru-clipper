from __future__ import annotations

from fastapi import APIRouter

from app.services.runtime_capabilities import get_cached_runtime_capabilities

router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/capabilities")
def runtime_capabilities() -> dict[str, object]:
    return get_cached_runtime_capabilities()
