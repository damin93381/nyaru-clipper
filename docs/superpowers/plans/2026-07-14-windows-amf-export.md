# Windows AMF Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in Windows AMD AMF export path for confirmed clips, with safe CPU fallback and durable execution metadata.

**Architecture:** Keep task validation, database persistence, and HTTP contracts in `clip_export.py`. Add a focused encoding service that owns command selection and Windows path translation. The service returns the actual backend/encoder after using AMF or falling back once to the established CPU command.

**Tech Stack:** Python 3.11, Pydantic Settings, FastAPI/SQLModel, pytest, WSL interop (`wslpath`), Windows FFmpeg AMF.

## Global Constraints

- Default behavior stays CPU `libx264`; `windows-amf` is opt-in.
- The configured Windows FFmpeg executable must be passed as an argument list, never through a shell.
- Convert only runtime media paths with `wslpath -w`; redact converted source paths in logs.
- Preserve the current audio codec (`aac`), clip range semantics, artifact route, and task event contract.
- On AMF setup/process/output failure, run one CPU fallback and record the actual encoder.
- Keep English and zh-CN operator/deployment docs paired.

---

### Task 1: Model encoding configuration and command execution

**Files:**
- Modify: `backend/app/settings.py`
- Create: `backend/app/services/export_encoding.py`
- Test: `backend/tests/test_export_encoding.py`

**Interfaces:**
- Consumes: `Settings`, `run_logged_command`, `append_stage_log`
- Produces: `ExportInvocation`, `ExportExecution`, `execute_video_export(invocation, settings, log_path)`

- [ ] **Step 1: Write failing tests**

```python
def test_execute_video_export_uses_h264_amf_when_windows_backend_is_configured(...):
    ...
    assert execution.video_encoder == "h264_amf"
    assert "h264_amf" in commands[0]
    assert r"\\wsl.localhost\Ubuntu-22.04\source.mp4" in commands[0]

def test_execute_video_export_falls_back_to_libx264_after_amf_failure(...):
    ...
    assert ["h264_amf", "libx264"] == [command[command.index("-c:v") + 1] for command in commands]
    assert execution.video_encoder == "libx264"
```

- [ ] **Step 2: Run the focused tests and confirm they fail because the service does not exist**

Run: `PYTHONPATH=backend backend/.venv/bin/python -m pytest -s -q backend/tests/test_export_encoding.py`

Expected: import failure for `app.services.export_encoding`.

- [ ] **Step 3: Add minimal typed settings and execution service**

```python
class Settings(BaseSettings):
    export_video_backend: Literal["cpu", "windows-amf"] = "cpu"
    windows_ffmpeg_binary: Path | None = None

@dataclass(frozen=True, slots=True)
class ExportInvocation:
    source_path: Path
    output_path: Path
    start_s: float
    end_s: float
    source_reference: str
```

Construct AMF arguments only when both settings select it and provide an executable. Use `wslpath -w` for source and output. On a conversion/process/output failure, append a stable fallback log line and execute the CPU command once.

- [ ] **Step 4: Run focused tests and confirm they pass**

Run: `PYTHONPATH=backend backend/.venv/bin/python -m pytest -s -q backend/tests/test_export_encoding.py`

Expected: all tests pass.

### Task 2: Integrate actual encoder metadata into clip export

**Files:**
- Modify: `backend/app/services/clip_export.py`
- Modify: `backend/tests/test_clip_export.py`

**Interfaces:**
- Consumes: `execute_video_export(ExportInvocation, Settings, Path)`
- Produces: export artifact metadata fields `export_backend` and `video_encoder`

- [ ] **Step 1: Write failing integration assertions**

```python
assert artifact_metadata["export_backend"] == "cpu"
assert artifact_metadata["video_encoder"] == "libx264"
```

- [ ] **Step 2: Run the focused export test and confirm it fails on absent metadata**

Run: `PYTHONPATH=backend backend/.venv/bin/python -m pytest -s -q backend/tests/test_clip_export.py::test_export_confirmed_range`

Expected: `KeyError` for `export_backend`.

- [ ] **Step 3: Delegate subprocess selection to the encoding service and persist its result**

Replace the inline FFmpeg command in `export_confirmed_clip` with one `ExportInvocation`. Keep existing failure-stage semantics only when the final selected/fallback process fails. Include the returned backend and encoder in `_persist_export_artifact` metadata.

- [ ] **Step 4: Run focused export tests and confirm they pass**

Run: `PYTHONPATH=backend backend/.venv/bin/python -m pytest -s -q backend/tests/test_clip_export.py backend/tests/test_clip_export_api.py`

Expected: all tests pass.

### Task 3: Document and verify the WSL-to-Windows route

**Files:**
- Modify: `docs/operator-manual.md`
- Modify: `docs/operator-manual.zh-CN.md`
- Modify: `docs/deployment-guide.md`
- Modify: `docs/deployment-guide.zh-CN.md`

- [ ] **Step 1: Document opt-in configuration and fallback semantics**

Include the exact current executable configuration, the required `h264_amf` verification command, the WSL path conversion behavior, and the CPU fallback rule. State that only export is accelerated.

- [ ] **Step 2: Run source and regression verification**

Run:

```bash
bash -n scripts/*.sh
PYTHONPATH=backend backend/.venv/bin/python -m pytest -s -q \
  backend/tests/test_export_encoding.py \
  backend/tests/test_clip_export.py \
  backend/tests/test_clip_export_api.py
```

Expected: zero failures.

- [ ] **Step 3: Run a real AMF export of the downloaded Bilibili task**

Set `APP_EXPORT_VIDEO_BACKEND=windows-amf` and `APP_WINDOWS_FFMPEG_BINARY` to the verified executable. Export an existing clip candidate through the API, then confirm the task export log records `h264_amf`, the output exists, and the persisted artifact metadata says `video_encoder=h264_amf`.
