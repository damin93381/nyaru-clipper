from __future__ import annotations

import subprocess
from pathlib import Path


def _build_invocation(tmp_path: Path):
    from app.services.export_encoding import ExportInvocation

    return ExportInvocation(
        source_path=tmp_path / "source.mp4",
        output_path=tmp_path / "exports" / "clip.mp4",
        start_s=12.5,
        end_s=20.0,
        source_reference="managed-source.mp4",
    )


def test_execute_video_export_uses_h264_amf_when_windows_backend_is_configured(tmp_path, monkeypatch) -> None:
    # Given: a configured Windows FFmpeg executable and WSL paths that can be translated.
    from app.settings import Settings
    from app.services import export_encoding

    invocation = _build_invocation(tmp_path)
    commands: list[list[str]] = []
    redactions: list[dict[str, str] | None] = []

    def fake_convert(path: Path) -> str:
        return rf"\\wsl.localhost\Ubuntu-22.04\{path.name}"

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        redactions.append(kwargs.get("redactions"))
        invocation.output_path.parent.mkdir(parents=True, exist_ok=True)
        invocation.output_path.write_bytes(b"amf-output")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(export_encoding, "_convert_wsl_path", fake_convert)
    monkeypatch.setattr(export_encoding, "run_logged_command", fake_run)

    # When: the export is requested through the Windows AMF backend.
    execution = export_encoding.execute_video_export(
        invocation,
        Settings(
            export_video_backend="windows-amf",
            windows_ffmpeg_binary=Path("/mnt/e/ffmpeg.exe"),
        ),
        tmp_path / "export.log",
    )

    # Then: the AMF command uses translated paths and records the hardware encoder.
    assert execution.export_backend == "windows-amf"
    assert execution.video_encoder == "h264_amf"
    assert commands == [
        [
            "/mnt/e/ffmpeg.exe",
            "-y",
            "-ss",
            "12.500",
            "-to",
            "20.000",
            "-i",
            r"\\wsl.localhost\Ubuntu-22.04\source.mp4",
            "-c:v",
            "h264_amf",
            "-c:a",
            "aac",
            r"\\wsl.localhost\Ubuntu-22.04\clip.mp4",
        ]
    ]
    assert redactions == [{
        str(invocation.source_path): "managed-source.mp4",
        r"\\wsl.localhost\Ubuntu-22.04\source.mp4": "managed-source.mp4",
    }]


def test_execute_video_export_falls_back_to_libx264_after_amf_failure(tmp_path, monkeypatch) -> None:
    # Given: AMF process failure followed by a working CPU encoder.
    from app.settings import Settings
    from app.services import export_encoding

    invocation = _build_invocation(tmp_path)
    commands: list[list[str]] = []

    monkeypatch.setattr(export_encoding, "_convert_wsl_path", lambda path: rf"\\wsl.localhost\Ubuntu-22.04\{path.name}")

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        if "h264_amf" in args:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="AMF initialization failed")
        invocation.output_path.parent.mkdir(parents=True, exist_ok=True)
        invocation.output_path.write_bytes(b"cpu-output")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(export_encoding, "run_logged_command", fake_run)

    # When: the configured AMF process fails.
    execution = export_encoding.execute_video_export(
        invocation,
        Settings(
            export_video_backend="windows-amf",
            windows_ffmpeg_binary=Path("/mnt/e/ffmpeg.exe"),
        ),
        tmp_path / "export.log",
    )

    # Then: exactly one CPU fallback succeeds and is reported as the actual encoder.
    assert execution.export_backend == "cpu"
    assert execution.video_encoder == "libx264"
    assert [command[command.index("-c:v") + 1] for command in commands] == ["h264_amf", "libx264"]
    assert "export_backend_fallback=windows-amf_to_cpu reason=amf_process_failed" in (tmp_path / "export.log").read_text(
        encoding="utf-8"
    )


def test_execute_video_export_falls_back_to_libx264_when_windows_binary_is_unconfigured(tmp_path, monkeypatch) -> None:
    # Given: the AMF backend is selected without a Windows executable path.
    from app.settings import Settings
    from app.services import export_encoding

    invocation = _build_invocation(tmp_path)

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        invocation.output_path.parent.mkdir(parents=True, exist_ok=True)
        invocation.output_path.write_bytes(b"cpu-output")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(export_encoding, "run_logged_command", fake_run)

    # When: command selection is attempted.
    execution = export_encoding.execute_video_export(
        invocation,
        Settings(export_video_backend="windows-amf"),
        tmp_path / "export.log",
    )

    # Then: the request reaches the established CPU command rather than failing configuration validation.
    assert execution.export_backend == "cpu"
    assert execution.video_encoder == "libx264"


def test_execute_video_export_falls_back_to_libx264_when_windows_ffmpeg_cannot_launch(tmp_path, monkeypatch) -> None:
    # Given: a configured AMF binary that cannot be launched and a working CPU binary.
    from app.settings import Settings
    from app.services import export_encoding

    invocation = _build_invocation(tmp_path)
    commands: list[list[str]] = []

    monkeypatch.setattr(export_encoding, "_convert_wsl_path", lambda path: rf"\\wsl.localhost\Ubuntu-22.04\{path.name}")

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        if "h264_amf" in args:
            raise FileNotFoundError("Windows FFmpeg executable is unavailable")
        invocation.output_path.parent.mkdir(parents=True, exist_ok=True)
        invocation.output_path.write_bytes(b"cpu-output")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(export_encoding, "run_logged_command", fake_run)

    # When: the configured Windows executable cannot launch.
    execution = export_encoding.execute_video_export(
        invocation,
        Settings(
            export_video_backend="windows-amf",
            windows_ffmpeg_binary=Path("/mnt/e/missing-ffmpeg.exe"),
        ),
        tmp_path / "export.log",
    )

    # Then: the exporter reports the CPU attempt rather than leaking a launch exception.
    assert execution.export_backend == "cpu"
    assert execution.video_encoder == "libx264"
    assert [command[command.index("-c:v") + 1] for command in commands] == ["h264_amf", "libx264"]
    assert "export_backend_fallback=windows-amf_to_cpu reason=amf_launch_failed" in (tmp_path / "export.log").read_text(
        encoding="utf-8"
    )
