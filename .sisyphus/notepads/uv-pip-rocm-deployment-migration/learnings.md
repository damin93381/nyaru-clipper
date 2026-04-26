## 2026-04-25T18:41:02Z Task: session-start
- Canonical local workflow must become uv+pnpm, with Docker retained only as fallback.
- WSL+ROCm support is in scope and expected to cover full project functionality, but capability checks must warn instead of blocking startup.
- Capability status must be visible in API, UI, and logs.
- Python dependency source of truth remains backend/pyproject.toml; requirements.txt must be generated, not hand-maintained.

## 2026-04-25T18:49:33Z Task: add-uv-first-local-startup-command-surface
- New local script surface lives in scripts/dev_up.sh, dev_api.sh, dev_worker.sh, and dev_web.sh with one shared helper in scripts/_dev_common.sh.
- Host-side defaults intentionally mirror docker-compose topology: API uses APP_HOST/APP_PORT defaulting to 0.0.0.0:8000, web uses VITE_HOST/VITE_PORT defaulting to 0.0.0.0:5173, and VITE_API_BASE_URL defaults to http://127.0.0.1:8000/api.
- Backend local scripts must pre-create repo-local data and model-cache directories and export APP_DATA_DIR/APP_WHISPERX_MODEL_CACHE_DIR/HF_HOME/TRANSFORMERS_CACHE so backend/app/paths.py remains compatible outside containers.
- Full-stack startup should keep release_smoke.sh ordering: validate host commands first, start API first, wait for /api/health, then start worker and web.

## 2026-04-25T19:00:30Z Task: backend-app-models-compatibility-fix
- Confirmed the Task 1 blocker was pre-existing backend breakage, not introduced by scripts: app.main and app.db.init_db both depended on a missing app.models module.
- Restored backend/app/models.py as the canonical compatibility export surface expected by existing backend imports and tests.
- Explicit exports now include: Artifact, CANONICAL_STAGES, ClipCandidate, TERMINAL_STATUSES, Task, TaskJob, TaskStage, utc_now.
- Verified `uv run --project backend python -c "from app.main import app; print(app.title)"` and a live uvicorn `/api/health` request both succeed after the fix.

## 2026-04-25T19:14:26Z Task: backend-runtime-profile-and-capability-detection
- Runtime classification is now fact-driven: WSL is inferred from kernel/proc-version/env hints, while accelerator backend comes from torch runtime metadata (`torch.version.cuda`, `torch.version.hip`, `torch.cuda.is_available()`) rather than settings defaults.
- Capability payload ordering is intentionally stable for API/tests: top-level keys are `status`, `detected_profile`, `platform`, `accelerator`, `dependencies`, `warnings`, and dependency groups are split into deterministic `tools` and `python` maps.
- Missing GPU runtime and host tools are warning-only, but missing core Python libraries (`torch`, `transformers`, `whisperx`) escalate payload status to `error`; the diarization path (`pyannote.audio`) stays warning-only.

## 2026-04-26T00:00:00Z Task: generated-pip-compatibility-artifact
- `uv export --project backend --format requirements.txt --locked --no-dev --no-header --no-annotate --no-editable --no-hashes` is sufficient to derive the backend pip artifact from the canonical uv dependency graph, but it emits the first-party backend package as a bare `.` line.
- For a checked-in `backend/requirements.txt` that contributors install from the repo root with `pip install -r backend/requirements.txt`, the local project reference must be normalized to `./backend`; raw `.` and `-e .` are resolved relative to the current working directory and fail from the repo root.
- Fresh pip compatibility verification must use Python 3.11, not the host default blindly, because backend metadata currently requires `>=3.11,<3.12` and pip correctly rejects 3.12 during local package installation.

## 2026-04-26T02:40:00Z Task: worker-runtime-warnings
- Worker preflight warning surfacing fits the existing backend contract best as a single stable stage-log line instead of a schema change: `worker_preflight_warning=<json>`.
- `list_task_log_summaries()` returns the last non-empty log line for a stage, so warning visibility must be preserved after `run_task_pipeline()` writes its normal completion line; appending the same warning line again after pipeline execution keeps summaries deterministic.
- Retry behavior already clears `TaskStage.summary`, so worker capability warnings must be regenerated from the live capability service on each claimed attempt rather than relying on persisted summary state.

## 2026-04-25T19:45:38Z Task: capability-api-and-startup-status
- Added `app.services.runtime_capabilities` as the shared cached access layer so `/api/health`, `/api/runtime/capabilities`, and startup logs all derive from the same Task 2 payload source.
- `/api/health` stays readiness-oriented and returns the original keys plus an additive `runtime_capabilities` summary containing only `status`, `detected_profile`, and `warnings`; the full stable payload is exposed unchanged at `/api/runtime/capabilities`.

## 2026-04-25T20:09:26Z Task: web-environment-status-surface
- The minimal shell-integrated status surface fits best in the left `AppShell` rail above the reserved future task-list panel, reusing existing `panel`, `eyebrow`, `pill`, and `status-badge` styling so warning visibility is persistent without blocking main task views.
- For this repo, `pnpm --dir web test -- --run ...` must be executed with `CI=1` to avoid lingering in Vitest watch mode, and Vitest must explicitly exclude `web/e2e/**` so targeted unit-test runs do not accidentally ingest Playwright specs.

## 2026-04-26T03:59:48Z Task: deployment-docs-and-indexes
- Deployment guidance now treats `uv + pnpm` as the first-read and first-run path across the top-level README, docs indexes, deployment guides, and operator manuals, while keeping Docker explicitly labeled as fallback only.
- The deployment guides now document the exact support matrix expected by the repo implementation: `linux-cuda` as the primary host path, `wsl-rocm` as the full-function WSL target, Python 3.11 pip compatibility as a backend install path, and Docker fallback as a non-default alternative.
- Warning semantics are documented against the actual runtime surfaces: `/api/health` summary, `/api/runtime/capabilities` full payload, `app.runtime` startup log event `runtime_capabilities_startup`, and worker stage-log lines beginning with `worker_preflight_warning=`.

## 2026-04-26T12:06:00Z Task: smoke-verification-followup
- `./scripts/release_smoke_non_docker.sh` now verifies end-to-end successfully in this environment with fresh `EXIT=0`, including API health, web readiness, host media-tool discovery, backend pipeline smoke, frontend unit tests, frontend build, and targeted Playwright task-flow smoke.
- The non-Docker smoke path resolves `BBDown` and `yt-dlp` through repo-local `.bin/` shims in this workspace, so the earlier host-tool blocker is no longer active for Task 7 verification.
- `./scripts/release_smoke_docker.sh` remains environment-blocked here before container startup because this WSL distro cannot access Docker Desktop integration, even though the script syntax and compose-validation step are intact.

## 2026-04-26T04:47:00Z Task: runtime-capabilities-live-browser-fix
- The verified live bug was not the API client shape by itself; it was the missing browser boundary support for the uv-first dev origin. Keeping `web/src/lib/api.ts` on the explicit `http://127.0.0.1:8000/api` base is acceptable for this architecture as long as the backend explicitly allows the Vite dev origins via CORS.
- A useful TDD boundary for this class of bug is: web test proves which URL the client calls, backend test proves the browser preflight succeeds, and a live `scripts/dev_api.sh` check confirms the actual `OPTIONS /api/runtime/capabilities` response includes `Access-Control-Allow-Origin` for `http://127.0.0.1:5173`.

## 2026-04-26T04:54:27Z Task: verification-blockers-update
- The prior final-wave CORS rejection is now resolved by backend CORS support, backend preflight regression coverage, and live `OPTIONS /api/runtime/capabilities` evidence from the Vite dev origin.
