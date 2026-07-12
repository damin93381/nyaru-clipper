from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
from shutil import which

from app.services.runtime_diagnostics import derive_runtime_diagnostics
from app.services.runtime_profile import detect_runtime_profile
from app.settings import get_settings


def _which(binary: str) -> str | None:
    return which(binary)


def _import_module(module_name: str):
    return importlib.import_module(module_name)


def _find_module_spec(module_name: str):
    return importlib.util.find_spec(module_name)


def _read_distribution_version(distribution_name: str) -> str | None:
    try:
        return importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _dependency_warning_message(*, dependency_name: str, module_name: str, error: Exception | None = None) -> str:
    if error is None:
        if dependency_name == "whisperx_diarization":
            return "Python dependency path for WhisperX diarization ('pyannote.audio') is unavailable."
        return f"Python dependency '{module_name}' is not installed."

    if dependency_name == "whisperx_diarization":
        return f"Python dependency path for WhisperX diarization ('pyannote.audio') failed to import: {error}"
    return f"Python dependency '{module_name}' failed to import: {error}"


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
        if dependency_name == "whisperx_diarization":
            if _find_module_spec(module_name) is None:
                payload[dependency_name] = {
                    "available": False,
                    "module": module_name,
                    "status": "warning",
                    "version": None,
                }
                warnings.append(
                    _dependency_warning_message(dependency_name=dependency_name, module_name=module_name)
                )
                continue

            payload[dependency_name] = {
                "available": True,
                "module": module_name,
                "status": "ok",
                "version": _read_distribution_version("pyannote.audio"),
            }
            continue

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
            warnings.append(_dependency_warning_message(dependency_name=dependency_name, module_name=module_name))
            has_error = has_error or is_core
            continue
        except Exception as error:
            is_core = dependency_name in core_dependencies
            status = "error" if is_core else "warning"
            payload[dependency_name] = {
                "available": False,
                "module": module_name,
                "status": status,
                "version": None,
            }
            warnings.append(
                _dependency_warning_message(dependency_name=dependency_name, module_name=module_name, error=error)
            )
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
    runtime_issues, runtime_warnings, runtime_errors = derive_runtime_diagnostics(runtime_profile)

    warnings: list[str] = []
    warnings.extend(runtime_warnings)
    warnings.extend(tool_warnings)
    warnings.extend(python_warnings)

    return {
        "status": _derive_status(warnings=warnings, has_error=tool_errors or python_errors or runtime_errors),
        "detected_profile": runtime_profile["detected_profile"],
        "platform": runtime_profile["platform"],
        "accelerator": runtime_profile["accelerator"],
        "dependencies": {
            "tools": tool_payload,
            "python": python_payload,
        },
        "warnings": warnings,
        "issues": runtime_issues,
    }
