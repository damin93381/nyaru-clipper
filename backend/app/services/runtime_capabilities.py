from __future__ import annotations

from functools import lru_cache

from app.services.capability_checks import get_runtime_capabilities


@lru_cache(maxsize=1)
def get_cached_runtime_capabilities() -> dict[str, object]:
    return get_runtime_capabilities()


def get_runtime_capability_summary() -> dict[str, object]:
    payload = get_cached_runtime_capabilities()
    return {
        "status": payload["status"],
        "detected_profile": payload["detected_profile"],
        "warnings": list(payload["warnings"]),
    }


def reset_runtime_capabilities_cache() -> None:
    get_cached_runtime_capabilities.cache_clear()
