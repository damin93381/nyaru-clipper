from __future__ import annotations

import importlib
import os
import platform
from collections.abc import Mapping


def _load_torch_module():
    return importlib.import_module("torch")


def _read_proc_version() -> str:
    try:
        with open("/proc/version", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _is_wsl(*, release: str, version: str, proc_version: str) -> bool:
    if os.getenv("WSL_DISTRO_NAME"):
        return True

    candidates = (release, version, proc_version)
    return any("microsoft" in candidate.lower() or "wsl" in candidate.lower() for candidate in candidates if candidate)


def _safe_device_count(cuda_runtime: object) -> int:
    device_count = getattr(cuda_runtime, "device_count", None)
    if not callable(device_count):
        return 0

    try:
        count = device_count()
    except Exception:
        return 0

    return count if isinstance(count, int) and count >= 0 else 0


def _safe_is_available(cuda_runtime: object) -> bool:
    is_available = getattr(cuda_runtime, "is_available", None)
    if not callable(is_available):
        return False

    try:
        return bool(is_available())
    except Exception:
        return False


def _detect_accelerator(torch_module: object) -> dict[str, bool | int | str | None]:
    torch_version = getattr(torch_module, "__version__", None)
    version_info = getattr(torch_module, "version", None)
    cuda_version = getattr(version_info, "cuda", None) if version_info is not None else None
    hip_version = getattr(version_info, "hip", None) if version_info is not None else None

    cuda_runtime = getattr(torch_module, "cuda", None)
    available = _safe_is_available(cuda_runtime)
    device_count = _safe_device_count(cuda_runtime)

    backend = "unknown"
    kind = "unknown"
    if hip_version and available:
        backend = "rocm"
        kind = "cuda"
    elif cuda_version and available:
        backend = "cuda"
        kind = "cuda"
    elif not available:
        backend = "cpu"
        kind = "cpu"

    return {
        "available": available,
        "backend": backend,
        "cuda_version": cuda_version,
        "device_count": device_count,
        "hip_version": hip_version,
        "kind": kind,
        "torch_available": True,
        "torch_version": torch_version,
    }


def _detect_profile(*, is_wsl: bool, accelerator: Mapping[str, object]) -> str:
    available = bool(accelerator.get("available"))
    hip_version = accelerator.get("hip_version")
    cuda_version = accelerator.get("cuda_version")
    torch_available = bool(accelerator.get("torch_available"))

    if is_wsl and hip_version and available:
        return "wsl-rocm"
    if not is_wsl and cuda_version and available:
        return "linux-cuda"
    if torch_available and not available:
        return "cpu-only"
    return "unknown"


def detect_runtime_profile() -> dict[str, object]:
    release = platform.release()
    version = platform.version()
    proc_version = _read_proc_version()
    is_wsl = _is_wsl(release=release, version=version, proc_version=proc_version)
    platform_payload = {
        "is_wsl": is_wsl,
        "machine": platform.machine(),
        "release": release,
        "system": platform.system().lower(),
        "version": version,
    }

    try:
        torch_module = _load_torch_module()
    except ModuleNotFoundError:
        accelerator = {
            "available": False,
            "backend": "unknown",
            "cuda_version": None,
            "device_count": 0,
            "hip_version": None,
            "kind": "unknown",
            "torch_available": False,
            "torch_version": None,
        }
        return {
            "detected_profile": "unknown",
            "platform": platform_payload,
            "accelerator": accelerator,
        }

    accelerator = _detect_accelerator(torch_module)
    return {
        "detected_profile": _detect_profile(is_wsl=is_wsl, accelerator=accelerator),
        "platform": platform_payload,
        "accelerator": accelerator,
    }
