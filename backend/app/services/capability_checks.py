from __future__ import annotations

import importlib
from shutil import which

from app.services.runtime_profile import detect_runtime_profile
from app.settings import get_settings


def _which(binary: str) -> str | None:
    return which(binary)


def _import_module(module_name: str):
    return importlib.import_module(module_name)


def _build_tool_checks() -> tuple[dict[str, dict[str, str | bool | None]], list[str], bool]:
    settings = get_settings()
    configured_binaries = {
        "ffmpeg": settings.ffmpeg_binary,
        "ffprobe": settings.ffprobe_binary,
        "yt-dlp": settings.ytdlp_binary,
        "BBDown": settings.bbdown_binary,
    }

    payload: dict[str, dict[str, str | bool | None]] = {}
    warnings: list[str] = []
    has_error = False

    for tool_name, binary_name in configured_binaries.items():
        resolved_path = _which(binary_name)
        available = resolved_path is not None
        status = "ok" if available else "warning"
        payload[tool_name] = {
            "available": available,
            "binary": binary_name,
            "path": resolved_path,
            "status": status,
        }
        if not available:
            warnings.append(f"System tool '{tool_name}' was not found on PATH.")

    return payload, warnings, has_error


def _build_python_checks() -> tuple[dict[str, dict[str, str | bool | None]], list[str], bool]:
    module_names = {
        "torch": "torch",
        "transformers": "transformers",
        "whisperx": "whisperx",
        "whisperx_diarization": "pyannote.audio",
    }
    core_dependencies = {"torch", "transformers", "whisperx"}

    payload: dict[str, dict[str, str | bool | None]] = {}
    warnings: list[str] = []
    has_error = False

    for dependency_name, module_name in module_names.items():
        try:
            module = _import_module(module_name)
        except ModuleNotFoundError:
            is_core = dependency_name in core_dependencies
            status = "error" if is_core else "warning"
            payload[dependency_name] = {
                "available": False,
                "module": module_name,
                "status": status,
                "version": None,
            }
            if dependency_name == "whisperx_diarization":
                warnings.append("Python dependency path for WhisperX diarization ('pyannote.audio') is unavailable.")
            else:
                warnings.append(f"Python dependency '{module_name}' is not installed.")
            has_error = has_error or is_core
            continue

        payload[dependency_name] = {
            "available": True,
            "module": module_name,
            "status": "ok",
            "version": getattr(module, "__version__", None),
        }

    return payload, warnings, has_error


def _derive_status(*, warnings: list[str], has_error: bool) -> str:
    if has_error:
        return "error"
    if warnings:
        return "warning"
    return "ok"


def get_runtime_capabilities() -> dict[str, object]:
    runtime_profile = detect_runtime_profile()
    tool_payload, tool_warnings, tool_errors = _build_tool_checks()
    python_payload, python_warnings, python_errors = _build_python_checks()

    warnings: list[str] = []
    if runtime_profile["detected_profile"] == "cpu-only":
        warnings.append("GPU runtime was not detected; backend is operating in cpu-only mode.")

    warnings.extend(tool_warnings)
    warnings.extend(python_warnings)

    return {
        "status": _derive_status(warnings=warnings, has_error=tool_errors or python_errors),
        "detected_profile": runtime_profile["detected_profile"],
        "platform": runtime_profile["platform"],
        "accelerator": runtime_profile["accelerator"],
        "dependencies": {
            "tools": tool_payload,
            "python": python_payload,
        },
        "warnings": warnings,
    }
