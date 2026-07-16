# Windows AMF Export Design

## Goal

Allow the WSL workstation to export a confirmed clip with Windows AMD AMF H.264 encoding, while preserving the existing Linux `libx264` export as the default and automatic fallback.

## Scope

- Add an opt-in `APP_EXPORT_VIDEO_BACKEND=windows-amf` setting.
- Require `APP_WINDOWS_FFMPEG_BINARY` to identify a Windows `ffmpeg.exe`; no PATH discovery is performed at export time.
- Convert the WSL source and output paths with `wslpath -w` before invoking the configured executable with `h264_amf`.
- If path conversion, AMF invocation, or AMF output validation fails, log the reason and run the current `libx264` command.
- Persist the actual video encoder in export artifact metadata.
- Keep the API response, clip format, audio codec (`aac`), range validation, task lifecycle, and CPU-only hosts unchanged.

## Non-goals

- No change to ASR, media preparation, video decoding, download, or task queue concurrency.
- No VAAPI implementation in WSL.
- No automatic Windows FFmpeg discovery, Windows package installation, or frontend settings UI in this pass.
- No GPU availability check at server startup; AMF is verified at the export boundary and falls back safely.

## Architecture

`clip_export.py` continues to own task/database state and artifact persistence. A new focused export-encoding service owns command selection, WSL-to-Windows path conversion, AMF execution, logging of fallback causes, and returning the actual encoder used.

The service constructs immutable request/result values. For `windows-amf`, it invokes the explicitly configured executable with converted source/output paths and `-c:v h264_amf`. A nonzero process result or missing output triggers exactly one CPU `libx264` attempt. The CPU backend remains the default and does not execute Windows tooling.

## Configuration

```bash
APP_EXPORT_VIDEO_BACKEND=windows-amf
APP_WINDOWS_FFMPEG_BINARY='/mnt/e/Program Files/ffmpeg-N-125573-g90436de5e1-win64-gpl-shared/bin/ffmpeg.exe'
```

`APP_EXPORT_VIDEO_BACKEND` accepts `cpu` (default) or `windows-amf`. An empty `APP_WINDOWS_FFMPEG_BINARY` with `windows-amf` is a logged fallback to CPU, not a task failure.

## Error Handling and Observability

The export stage log records the selected backend and any AMF fallback cause. Existing path redaction applies to the Windows-form source path too. Artifact metadata includes `video_encoder` (`h264_amf` or `libx264`) and `export_backend` (`windows-amf` or `cpu`) so reports and later UI work can expose the actual execution path.

## Validation

- Unit tests cover Windows command construction, missing configuration fallback, failed AMF process fallback, and CPU default behavior.
- Existing export tests continue to verify database and API behavior.
- On this host, run a real confirmed-clip export from the downloaded Bilibili task with the configured Windows executable, then inspect the artifact metadata and FFmpeg output.

## Decision Record

The Windows FFmpeg build at `E:\Program Files\ffmpeg-N-125573-g90436de5e1-win64-gpl-shared\bin\ffmpeg.exe` exposes `h264_amf`, `hevc_amf`, and `av1_amf`; a real 128x128 H.264 AMF encode succeeded. The WSL FFmpeg VAAPI device probe failed, so the implementation deliberately targets Windows AMF rather than WSL VAAPI.
