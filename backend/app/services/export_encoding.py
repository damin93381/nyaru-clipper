from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.services.pipeline_support import append_stage_log, run_logged_command
from app.settings import Settings


@dataclass(frozen=True, slots=True)
class ExportInvocation:
    source_path: Path
    output_path: Path
    start_s: float
    end_s: float
    source_reference: str


@dataclass(frozen=True, slots=True)
class ExportExecution:
    export_backend: str
    video_encoder: str
    completed_process: subprocess.CompletedProcess[str]


@dataclass(frozen=True, slots=True)
class _ExportCommandSpec:
    ffmpeg_binary: str
    source_path: str
    output_path: str
    start_s: float
    end_s: float
    video_encoder: str


class WindowsPathConversionError(RuntimeError):
    pass


def execute_video_export(invocation: ExportInvocation, settings: Settings, log_path: Path) -> ExportExecution:
    if settings.export_video_backend == "windows-amf":
        windows_ffmpeg_binary = settings.windows_ffmpeg_binary
        if windows_ffmpeg_binary is None:
            return _run_cpu_export(invocation, settings, log_path, fallback_reason="windows_ffmpeg_unconfigured")
        try:
            windows_command, windows_source_path = _build_windows_amf_command(invocation, windows_ffmpeg_binary)
        except WindowsPathConversionError:
            return _run_cpu_export(invocation, settings, log_path, fallback_reason="wslpath_failed")

        append_stage_log(log_path, "export_backend=windows-amf encoder=h264_amf")
        try:
            windows_result = run_logged_command(
                windows_command,
                log_path=log_path,
                redactions={
                    str(invocation.source_path): invocation.source_reference,
                    windows_source_path: invocation.source_reference,
                },
            )
        except OSError:
            return _run_cpu_export(invocation, settings, log_path, fallback_reason="amf_launch_failed")
        if windows_result.returncode == 0 and invocation.output_path.exists():
            return ExportExecution(
                export_backend="windows-amf",
                video_encoder="h264_amf",
                completed_process=windows_result,
            )
        fallback_reason = "amf_process_failed" if windows_result.returncode != 0 else "amf_output_missing"
        return _run_cpu_export(invocation, settings, log_path, fallback_reason=fallback_reason)
    return _run_cpu_export(invocation, settings, log_path)


def _run_cpu_export(
    invocation: ExportInvocation,
    settings: Settings,
    log_path: Path,
    *,
    fallback_reason: str | None = None,
) -> ExportExecution:
    if fallback_reason is not None:
        append_stage_log(log_path, f"export_backend_fallback=windows-amf_to_cpu reason={fallback_reason}")
    append_stage_log(log_path, "export_backend=cpu encoder=libx264")
    cpu_result = run_logged_command(
        _build_cpu_command(invocation, settings.ffmpeg_binary),
        log_path=log_path,
        redactions={str(invocation.source_path): invocation.source_reference},
    )
    return ExportExecution(export_backend="cpu", video_encoder="libx264", completed_process=cpu_result)


def _build_windows_amf_command(invocation: ExportInvocation, ffmpeg_binary: Path) -> tuple[list[str], str]:
    windows_source_path = _convert_wsl_path(invocation.source_path)
    windows_output_path = _convert_wsl_path(invocation.output_path)
    return _build_command(
        _ExportCommandSpec(
            ffmpeg_binary=str(ffmpeg_binary),
            source_path=windows_source_path,
            output_path=windows_output_path,
            start_s=invocation.start_s,
            end_s=invocation.end_s,
            video_encoder="h264_amf",
        )
    ), windows_source_path


def _build_cpu_command(invocation: ExportInvocation, ffmpeg_binary: str) -> list[str]:
    return _build_command(
        _ExportCommandSpec(
            ffmpeg_binary=ffmpeg_binary,
            source_path=str(invocation.source_path),
            output_path=str(invocation.output_path),
            start_s=invocation.start_s,
            end_s=invocation.end_s,
            video_encoder="libx264",
        )
    )


def _build_command(spec: _ExportCommandSpec) -> list[str]:
    return [
        spec.ffmpeg_binary,
        "-y",
        "-ss",
        f"{spec.start_s:.3f}",
        "-to",
        f"{spec.end_s:.3f}",
        "-i",
        spec.source_path,
        "-c:v",
        spec.video_encoder,
        "-c:a",
        "aac",
        spec.output_path,
    ]


def _convert_wsl_path(path: Path) -> str:
    try:
        result = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, check=False)
    except OSError as error:
        raise WindowsPathConversionError(str(error)) from error
    windows_path = result.stdout.strip()
    if result.returncode != 0 or not windows_path:
        raise WindowsPathConversionError(result.stderr.strip() or "wslpath did not return a Windows path")
    return windows_path
