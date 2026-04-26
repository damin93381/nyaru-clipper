from __future__ import annotations

from functools import lru_cache

from app.services.capability_checks import get_runtime_capabilities


@lru_cache(maxsize=1)
def get_cached_runtime_capabilities() -> dict[str, object]:
    return get_runtime_capabilities()


def get_runtime_capability_summary() -> dict[str, object]:
    payload = get_cached_runtime_capabilities()
    issues = payload.get("issues")
    issue_codes = [issue.get("code") for issue in issues if isinstance(issue, dict) and issue.get("code")] if isinstance(issues, list) else []
    accelerator_payload = payload.get("accelerator")
    accelerator_summary = {
        "available": accelerator_payload.get("available"),
        "backend": accelerator_payload.get("backend"),
        "device_count": accelerator_payload.get("device_count"),
        "device_name": accelerator_payload.get("device_name"),
        "torch_build_family": accelerator_payload.get("torch_build_family"),
    } if isinstance(accelerator_payload, dict) else {
        "available": None,
        "backend": None,
        "device_count": None,
        "device_name": None,
        "torch_build_family": None,
    }
    return {
        "status": payload["status"],
        "detected_profile": payload["detected_profile"],
        "accelerator": accelerator_summary,
        "warnings": list(payload["warnings"]),
        "issue_codes": issue_codes,
    }


def reset_runtime_capabilities_cache() -> None:
    get_cached_runtime_capabilities.cache_clear()
