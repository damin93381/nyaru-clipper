# UV-first Runtime, pip Compatibility, and WSL+ROCm Support Implementation Plan

## TL;DR
> **Summary**: Replace the repository’s Docker-first local workflow with a uv+pnpm primary path, add a generated pip compatibility artifact, preserve Docker as fallback, and add end-to-end WSL+ROCm capability detection plus visibility without blocking startup.
> **Deliverables**:
> - Non-Docker full-stack startup scripts plus split-process commands
> - Backend capability detection, API exposure, startup/task warnings, and log surfacing
> - Web environment-status UI
> - Generated `backend/requirements.txt` compatibility artifact
> - Detailed deployment guides for Linux+CUDA, WSL+ROCm, pip compatibility, and Docker fallback
> - Updated smoke/verification coverage for primary and fallback workflows
> **Effort**: XL
> **Parallel**: YES - 2 waves
> **Critical Path**: Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 7 → Task 8

## Context
### Original Request
- Analyze the current project and design an implementation plan for a uv-based non-Docker version.
- Add traditional `requirements.txt` / pip compatibility.
- Add a detailed deployment document.
- Add WSL+ROCm AMD GPU support, GPU checks, and ROCm library availability checks.
- Keep Docker only as fallback.
- Keep checks warning-only rather than startup-blocking.

### Interview Summary
- Keep existing `backend/` and `web/` boundaries; do not redesign the application architecture.
- Make `uv + pnpm` the canonical local workflow.
- Provide both one-command full-stack startup and split-process startup.
- Keep `pip/requirements.txt` as a compatibility path, not a second first-class development workflow.
- Keep Docker as fallback only.
- WSL+ROCm must support the full current project workflow; checks warn and surface status, but do not block startup.
- Status visibility must exist in API, UI, and logs.

### Metis Review (gaps addressed)
- Resolved support-surface explosion by explicitly choosing one canonical local workflow (`uv + pnpm`) and one compatibility path (`pip`).
- Resolved dependency drift risk by choosing `pyproject.toml` as the only Python dependency source of truth and making `requirements.txt` a generated, checked-in artifact.
- Resolved ROCm ambiguity by scoping WSL+ROCm validation to a named support profile with explicit task-level proof, not just install/import success.
- Resolved documentation scope by limiting detailed deployment docs to self-hosted/local environments already implied by the repo: Linux+CUDA, WSL+ROCm, pip compatibility, Docker fallback.
- Resolved warning-only risk by requiring structured status output in API/UI/logs and repeat checks before task execution.

## Work Objectives
### Core Objective
Make this repository operable primarily without Docker while preserving current functionality, adding a stable pip compatibility path, and introducing WSL+ROCm support that is observable, diagnosable, and validated against real task execution.

### Deliverables
- Root-level non-Docker startup command surface
- Backend runtime profile + capability detection service
- Capability API contract and startup/task warning logs
- Web environment status UI
- Generated `backend/requirements.txt`
- Updated smoke scripts for uv-first primary verification and Docker fallback verification
- Deployment guides in English and Chinese

### Definition of Done (verifiable conditions with commands)
- `./scripts/dev_up.sh` starts API, worker, and web without Docker and both `http://127.0.0.1:8000/api/health` and `http://127.0.0.1:5173` return `200`.
- `./scripts/dev_api.sh`, `./scripts/dev_worker.sh`, and `./scripts/dev_web.sh` can be run independently and interoperate.
- `uv run --project backend pytest backend/tests/test_runtime_capabilities.py -q` passes.
- `uv run --project backend pytest backend/tests/test_worker_runtime_warnings.py -q` passes.
- `pnpm --dir web test -- --run web/src/components/__tests__/EnvironmentStatusCard.test.tsx` passes.
- `./scripts/export_backend_requirements.sh` regenerates `backend/requirements.txt` without manual edits.
- `python3 -m venv .tmp-pip-smoke && . .tmp-pip-smoke/bin/activate && python -m pip install -r backend/requirements.txt && python -c "import fastapi, sqlmodel, transformers"` exits `0`.
- `./scripts/release_smoke_non_docker.sh` exits `0`.
- `./scripts/release_smoke_docker.sh` exits `0`.
- The deployment guides describe Linux+CUDA, WSL+ROCm, pip compatibility, and Docker fallback with explicit warning semantics and troubleshooting steps.

### Must Have
- Docker removed from the primary local workflow narrative and scripts.
- `backend/requirements.txt` generated from the existing uv/pyproject source of truth.
- Structured runtime capability payload available via backend API.
- Web UI exposure of capability status and warning messages.
- Worker warning behavior before task execution.
- WSL+ROCm-specific install and validation path documented in detail.
- Linux+CUDA behavior preserved as a non-regressed primary supported path.

### Must NOT Have
- Must NOT introduce CI/CD, cloud deployment, or infra automation.
- Must NOT hand-maintain Python dependencies in both `pyproject.toml` and `requirements.txt`.
- Must NOT make Docker the primary dev workflow again.
- Must NOT claim native Windows GPU support, macOS GPU support, or AMD Docker support.
- Must NOT block startup on failed GPU/ROCm checks; warnings only.
- Must NOT hide capability problems solely in logs; API/UI surfacing is required.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: tests-after with existing `pytest`, `Vitest`, `Playwright`, and smoke scripts
- QA policy: Every task includes agent-executed happy-path and failure-path scenarios
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.{ext}`

## Execution Strategy
### Parallel Execution Waves
> Target: 5-8 tasks per wave. <3 per wave (except final) = under-splitting.
> Extract shared dependencies as Wave-1 tasks for max parallelism.

Wave 1: foundation and contracts
- Task 1: Non-Docker command surface
- Task 2: Backend runtime profile and capability detection
- Task 3: Capability API and startup status logging
- Task 6: pip compatibility artifact generation

Wave 2: integration and user-facing surfaces
- Task 4: Worker runtime warnings and task-stage surfacing
- Task 5: Web capability status UI
- Task 7: Smoke/verification workflow refactor
- Task 8: Detailed deployment documentation

### Dependency Matrix (full, all tasks)
- Task 1 blocks Tasks 7 and 8
- Task 2 blocks Tasks 3, 4, 5, and 8
- Task 3 blocks Tasks 5, 7, and 8
- Task 4 blocks Task 7 and informs Task 8
- Task 5 depends on Task 3
- Task 6 informs Task 8 and Task 7
- Task 7 depends on Tasks 1, 3, 4, and 6
- Task 8 depends on Tasks 1, 3, 4, and 6

### Agent Dispatch Summary (wave → task count → categories)
- Wave 1 → 4 tasks → unspecified-high, senior-devops-style execution, quick wrappers
- Wave 2 → 4 tasks → unspecified-high, visual-engineering for UI, writing for docs

## TODOs
> Implementation + Test = ONE task. Never separate.
> EVERY task MUST have: Agent Profile + Parallelization + QA Scenarios.

- [x] 1. Add uv-first local startup command surface

  **What to do**: Introduce root-level non-Docker startup wrappers that make uv+pnpm the primary local path while preserving split-process usage. Add one full-stack command plus separate API/worker/web commands, shared env/bootstrap logic, and clear command names that can be referenced by docs and smoke tests.
  **Must NOT do**: Do not remove Docker files; do not introduce Make, Procfile managers, or task runners outside plain repo scripts.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: multi-file shell/script orchestration change with repo-wide impact
  - Skills: [`senior-devops`] - why needed: command-surface, environment bootstrap, local workflow design
  - Omitted: [`docker-development`] - why not needed: Docker remains fallback only, not the focus of this task

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [7, 8] | Blocked By: []

  **References** (executor has NO interview context - be exhaustive):
  - Pattern: `infra/docker-compose.yml:3-82` - current three-process topology and env/port/data expectations to mirror without Docker
  - Pattern: `infra/docker/api.Dockerfile:12-55` - backend runtime currently uses `uv sync --no-dev` and `uv run` entrypoints
  - Pattern: `web/package.json:10-15` - current frontend command surface (`dev`, `build`, `test`, `test:e2e`)
  - Pattern: `scripts/release_smoke.sh:67-93` - current smoke flow order that the non-Docker wrappers must support
  - API/Type: `backend/app/paths.py:7-19` - current host/container data-dir fallback behavior

  **Acceptance Criteria** (agent-executable only):
  - [ ] `./scripts/dev_up.sh` exists, starts API/worker/web without Docker, and exits nonzero on missing required host commands.
  - [ ] `./scripts/dev_api.sh`, `./scripts/dev_worker.sh`, and `./scripts/dev_web.sh` exist and can be run independently.
  - [ ] `./scripts/dev_up.sh` uses the same ports and task-data roots expected by existing web/API code.
  - [ ] `bash -n ./scripts/dev_up.sh ./scripts/dev_api.sh ./scripts/dev_worker.sh ./scripts/dev_web.sh` exits `0`.

  **QA Scenarios** (MANDATORY - task incomplete without these):
  ```
  Scenario: Full-stack non-Docker startup works
    Tool: Bash
    Steps: Run `./scripts/dev_up.sh` in background on a clean checkout after installing uv and pnpm deps; poll `http://127.0.0.1:8000/api/health` and `http://127.0.0.1:5173` until ready.
    Expected: Both endpoints return HTTP 200 and processes stay alive long enough for health verification.
    Evidence: .sisyphus/evidence/task-1-startup.txt

  Scenario: Missing host dependency is reported clearly
    Tool: Bash
    Steps: Temporarily run `PATH=/usr/bin ./scripts/dev_up.sh` in an environment that excludes `uv` or `pnpm`.
    Expected: Script exits nonzero with an actionable missing-command message naming the absent executable.
    Evidence: .sisyphus/evidence/task-1-missing-dependency.txt
  ```

  **Commit**: YES | Message: `feat(dev): add uv-first local startup scripts` | Files: `scripts/dev_up.sh`, `scripts/dev_api.sh`, `scripts/dev_worker.sh`, `scripts/dev_web.sh`, related shared script helpers

- [x] 2. Implement backend runtime profile and capability detection service

  **What to do**: Add a backend service that detects runtime profile (`linux-cuda`, `wsl-rocm`, `cpu-only`, `unknown`), checks GPU/runtime availability, verifies key Python libraries and system tools, and returns a structured capability payload plus warnings. Make defaults non-hardcoded in logic: current settings may still default to `cuda`, but the detection layer must classify runtime independently.
  **Must NOT do**: Do not rewrite task business logic; do not introduce startup blocking.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: backend runtime abstraction and profile detection
  - Skills: [`senior-devops`, `senior-ml-engineer`] - why needed: platform/runtime checks plus GPU stack awareness
  - Omitted: [`senior-architect`] - why not needed: architecture decision is already made

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [3, 4, 5, 8] | Blocked By: []

  **References**:
  - Pattern: `backend/app/settings.py:8-34` - current env-driven settings model and CUDA-biased defaults
  - Pattern: `backend/app/paths.py:7-19` - host-vs-container path detection pattern
  - Pattern: `backend/tests/test_asr_whisperx.py` - existing test style for configurable device behavior
  - Pattern: `backend/tests/test_translation_hf.py` - existing test style for device-aware translation service
  - API/Type: `backend/app/main.py:12-25` - current FastAPI lifespan hook where startup checks can be initialized or cached
  - External: AMD WSL ROCm support matrix/docs - use for version-bounded WSL+ROCm profile validation logic

  **Acceptance Criteria**:
  - [ ] New backend module returns a stable JSON-serializable payload with fields for `status`, `detected_profile`, `platform`, `accelerator`, `dependencies`, and `warnings`.
  - [ ] Detection distinguishes at minimum `linux-cuda`, `wsl-rocm`, `cpu-only`, and `unknown` using real runtime facts rather than config strings alone.
  - [ ] Tool checks cover `ffmpeg`, `ffprobe`, `yt-dlp`, and `BBDown`.
  - [ ] Python-library checks cover at least `torch`, `transformers`, `whisperx`, and the diarization dependency path.
  - [ ] `uv run --project backend pytest backend/tests/test_runtime_capabilities.py -q` passes.

  **QA Scenarios**:
  ```
  Scenario: Runtime profile classification succeeds for mocked environments
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_runtime_capabilities.py -q` with fixtures covering Linux+CUDA, WSL+ROCm, and CPU-only environments.
    Expected: Tests assert exact `detected_profile`, warning sets, and dependency/tool status fields.
    Evidence: .sisyphus/evidence/task-2-runtime-capabilities.txt

  Scenario: Missing ROCm or system tools produce warnings, not crashes
    Tool: Bash
    Steps: Run the same test module’s failure-path fixtures with `torch.cuda.is_available()` false or tool resolution returning null.
    Expected: Capability payload reports `warning`/`error` state inside the payload and includes actionable warning strings; process under test remains importable and does not raise at import time.
    Evidence: .sisyphus/evidence/task-2-warning-fixtures.txt
  ```

  **Commit**: YES | Message: `feat(runtime): add platform and capability detection` | Files: `backend/app/services/runtime_profile.py`, `backend/app/services/capability_checks.py`, `backend/tests/test_runtime_capabilities.py`, related support modules

- [x] 3. Expose capability status via API health contracts and startup logs

  **What to do**: Extend backend API so capability information is queryable and visible. Keep `/api/health` backward-compatible while adding a dedicated capabilities endpoint (for example `/api/runtime/capabilities`). Emit a structured startup summary to API logs and cache/recompute capability data in a deterministic way.
  **Must NOT do**: Do not break the existing `/api/health` smoke contract; do not make the health endpoint fail solely because capability checks warn.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: API contract addition plus startup integration
  - Skills: [`senior-backend`] - why needed: route design and payload consistency
  - Omitted: [`senior-devops`] - why not needed: task is now API contract integration rather than shell orchestration

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [5, 7, 8] | Blocked By: [2]

  **References**:
  - Pattern: `backend/app/api/routes/health.py:8-15` - existing health route must remain compatible
  - Pattern: `backend/app/api/routes/__init__.py:1-11` - current router registration pattern
  - Pattern: `backend/app/main.py:12-25` - lifespan hook and root route pattern
  - Test: `scripts/release_smoke.sh:73-79` - current smoke assertions against health endpoints and runtime tool visibility

  **Acceptance Criteria**:
  - [ ] `/api/health` still returns HTTP `200` with existing keys and may include additive non-breaking fields.
  - [ ] New capability endpoint returns HTTP `200` with exact keys matching the backend detection payload.
  - [ ] API startup logs include a single structured capability summary line or JSON object with profile/status/warnings.
  - [ ] `uv run --project backend pytest backend/tests/test_runtime_api.py -q` passes.

  **QA Scenarios**:
  ```
  Scenario: Health and capability endpoints remain stable
    Tool: Bash
    Steps: Start the API via `./scripts/dev_api.sh`; request `http://127.0.0.1:8000/api/health` and `http://127.0.0.1:8000/api/runtime/capabilities`.
    Expected: `/api/health` returns 200 with `status=ok`; capability endpoint returns 200 with profile/status/dependencies/warnings payload.
    Evidence: .sisyphus/evidence/task-3-api-contract.json

  Scenario: Warning-only capability failure does not break health readiness
    Tool: Bash
    Steps: Start API in a fixture environment where the capability service reports missing ROCm/tool dependencies; call both endpoints.
    Expected: `/api/health` remains 200; capability endpoint includes warnings and a non-`ok` capability status; startup logs include the warning summary.
    Evidence: .sisyphus/evidence/task-3-warning-health.txt
  ```

  **Commit**: YES | Message: `feat(api): expose runtime capability status` | Files: `backend/app/api/routes/health.py`, `backend/app/api/routes/runtime.py`, `backend/app/api/routes/__init__.py`, `backend/tests/test_runtime_api.py`, startup logging integration files

- [x] 4. Add worker preflight warnings and task-level capability surfacing

  **What to do**: Before worker execution of a claimed job, run a lightweight capability recheck and surface any mismatches into task-stage summaries/logs while allowing execution to continue. Keep the existing single-accelerator guard behavior, but make warnings explicit when the runtime profile does not satisfy expected GPU/ROCm conditions.
  **Must NOT do**: Do not rename or migrate persistence schema fields like `gpu_bound`; keep this change behavioral and observational.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: worker integration, task-state/logging changes, failure semantics
  - Skills: [`senior-backend`, `systematic-debugging`] - why needed: queue behavior and log-surface changes without regressions
  - Omitted: [`senior-architect`] - why not needed: schema strategy already decided

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [7, 8] | Blocked By: [2]

  **References**:
  - Pattern: `backend/app/worker.py:20-30` - current single running `gpu_bound` guard
  - Pattern: `backend/app/worker.py:87-110` - worker iteration and loop hook points for warning checks
  - Pattern: `backend/app/repositories/tasks.py:118-121` - all new jobs currently created with `gpu_bound=True`
  - Pattern: `backend/app/repositories/tasks.py:156-168` - current task-log summary response shape
  - Pattern: `backend/app/repositories/tasks.py:171-204` - retry path that must preserve warning behavior
  - Test: `backend/tests/test_task_runner.py`, `backend/tests/test_e2e_pipeline.py` - existing worker/pipeline regression patterns

  **Acceptance Criteria**:
  - [ ] Worker performs a pre-execution capability check before running `run_task_pipeline`.
  - [ ] Warning results are persisted to stage summaries and/or stage log output in a deterministic, parseable format.
  - [ ] Task retries preserve the same warning surfacing behavior.
  - [ ] `uv run --project backend pytest backend/tests/test_worker_runtime_warnings.py -q` passes.

  **QA Scenarios**:
  ```
  Scenario: Worker emits capability warnings before task execution
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_worker_runtime_warnings.py -q` with fixtures that simulate missing ROCm libraries or missing ffmpeg while keeping the worker runnable.
    Expected: Task/stage summaries include the expected warning text or structured warning payload, and the worker proceeds into the normal execution path.
    Evidence: .sisyphus/evidence/task-4-worker-warnings.txt

  Scenario: Retry path preserves warning visibility
    Tool: Bash
    Steps: Run a retry-specific fixture that resets a task and reclaims a job after a capability warning has been emitted.
    Expected: Retry response succeeds and the next stage log/summary still includes capability warning context for the rerun.
    Evidence: .sisyphus/evidence/task-4-retry-warnings.txt
  ```

  **Commit**: YES | Message: `feat(worker): surface runtime capability warnings` | Files: `backend/app/worker.py`, related logging/helpers, `backend/tests/test_worker_runtime_warnings.py`, possibly repository summary helpers

- [x] 5. Add web environment status surface for capability warnings

  **What to do**: Extend the frontend API/types layer to fetch runtime capabilities and render a persistent environment-status surface in the shell. It must show the active profile, overall status, warnings, and whether the environment satisfies the repository’s expected full-function profile.
  **Must NOT do**: Do not create a new page or dashboard; integrate into the existing shell/workspace layout with minimal UI surface area.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: user-facing status card/banner with existing React layout integration
  - Skills: [`senior-frontend`] - why needed: React Query + type-safe contract + UI state handling
  - Omitted: [`a11y-audit`] - why not needed: standard status card integration, not a dedicated a11y sweep

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [] | Blocked By: [3]

  **References**:
  - Pattern: `web/src/lib/api.ts:11-107` - existing API client conventions and error handling
  - Pattern: `web/src/lib/types.ts:16-98` - existing typed API contract conventions
  - Pattern: `web/src/components/AppShell.tsx:3-49` - best integration point for global environment-status UI
  - Pattern: `web/src/pages/WorkspacePage.tsx:248-260` - current panel/header styling patterns if a secondary panel is needed
  - Test: `web/src/pages/__tests__/WorkspacePage.test.tsx`, `web/src/pages/__tests__/TaskDetailPage.test.tsx` - existing frontend test style patterns

  **Acceptance Criteria**:
  - [ ] Frontend fetches capability status from the backend and renders it without blocking the main task views.
  - [ ] App shell visibly shows profile, status, and warning count/text.
  - [ ] Warning-only states are visually distinct from fully healthy states.
  - [ ] `pnpm --dir web test -- --run web/src/components/__tests__/EnvironmentStatusCard.test.tsx` passes.

  **QA Scenarios**:
  ```
  Scenario: Healthy environment status renders in shell
    Tool: Bash
    Steps: Run `pnpm --dir web test -- --run web/src/components/__tests__/EnvironmentStatusCard.test.tsx` with mocked API payload for `linux-cuda` or `wsl-rocm` status `ok`.
    Expected: Component shows the detected profile and healthy status copy without error styling.
    Evidence: .sisyphus/evidence/task-5-ui-healthy.txt

  Scenario: Warning state remains visible but non-blocking
    Tool: Bash
    Steps: Run the same test file with a mocked capability payload containing warnings and a non-`ok` status.
    Expected: Warning banner/card is rendered, warnings are visible in text, and no main navigation/task content is hidden.
    Evidence: .sisyphus/evidence/task-5-ui-warning.txt
  ```

  **Commit**: YES | Message: `feat(web): surface runtime capability status` | Files: `web/src/lib/api.ts`, `web/src/lib/types.ts`, `web/src/components/AppShell.tsx`, `web/src/components/EnvironmentStatusCard.tsx`, related tests/styles

- [x] 6. Add generated pip compatibility artifact and export workflow

  **What to do**: Introduce a deterministic export workflow that generates and commits `backend/requirements.txt` from the existing Python dependency source of truth. Add a wrapper script and regression checks so contributors do not hand-edit `requirements.txt`. Scope pip compatibility to backend installation/startup compatibility; do not promise WSL+ROCm full-function parity through pip.
  **Must NOT do**: Do not hand-maintain `requirements.txt`; do not introduce a second lockfile or a parallel pip-first dependency model.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: dependency artifact generation and compatibility contract work
  - Skills: [`senior-devops`] - why needed: reproducible export path and compatibility validation
  - Omitted: [`docker-development`] - why not needed: no container change required for this task

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [7, 8] | Blocked By: []

  **References**:
  - Pattern: `backend/pyproject.toml:1-35` - canonical Python dependency source of truth
  - Pattern: `backend/uv.lock` - current resolved uv dependency graph and CUDA-biased markers to preserve for the primary path
  - Pattern: `scripts/release_smoke.sh:9-14` - current required-command validation style for shell helpers
  - Pattern: `infra/docker/api.Dockerfile:42-47` - current backend install flow from pyproject/uv

  **Acceptance Criteria**:
  - [ ] `backend/requirements.txt` exists as a generated, checked-in artifact.
  - [ ] `./scripts/export_backend_requirements.sh` regenerates the file deterministically from the canonical dependency source.
  - [ ] A regression test or script detects when `backend/requirements.txt` is stale relative to the export command.
  - [ ] A fresh pip virtualenv can install backend dependencies from `backend/requirements.txt` and import the backend entry modules.

  **QA Scenarios**:
  ```
  Scenario: Requirements export is deterministic
    Tool: Bash
    Steps: Run `./scripts/export_backend_requirements.sh` twice and compare the resulting `backend/requirements.txt` contents.
    Expected: The second run produces no diff.
    Evidence: .sisyphus/evidence/task-6-requirements-export.txt

  Scenario: pip compatibility path installs and imports cleanly
    Tool: Bash
    Steps: Run `python3 -m venv .tmp-pip-smoke && . .tmp-pip-smoke/bin/activate && python -m pip install -r backend/requirements.txt && python -c "from app.main import app; print(app.title)"` from `backend/`-compatible PYTHONPATH context.
    Expected: pip install succeeds and the import/print command exits 0.
    Evidence: .sisyphus/evidence/task-6-pip-smoke.txt
  ```

  **Commit**: YES | Message: `build(python): export pip compatibility requirements` | Files: `backend/requirements.txt`, `scripts/export_backend_requirements.sh`, staleness-check script/test, related docs comments

- [x] 7. Refactor smoke and verification scripts to make non-Docker primary and Docker fallback explicit

  **What to do**: Replace the current Docker-first smoke entrypoint with a uv-first primary smoke flow and add a separate Docker fallback smoke flow. Preserve the existing runtime-tool verification and backend/frontend test coverage, but point the default smoke script at the new non-Docker command surface.
  **Must NOT do**: Do not delete Docker smoke coverage; do not leave the old `release_smoke.sh` semantics ambiguous.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: cross-stack verification orchestration and regression coverage refactor
  - Skills: [`senior-devops`, `verification-before-completion`] - why needed: workflow verification and evidence-driven smoke design
  - Omitted: [`playwright-pro`] - why not needed: existing Playwright usage is already established

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [8] | Blocked By: [1, 3, 4, 6]

  **References**:
  - Pattern: `scripts/release_smoke.sh:1-93` - current full smoke flow to preserve in split form
  - Pattern: `backend/app/api/routes/health.py:11-15` - health endpoint contract used by smoke scripts
  - Pattern: `web/package.json:10-15` - frontend test/build/e2e commands to reuse
  - Test: `backend/tests/test_e2e_pipeline.py` - backend smoke target already used by smoke script

  **Acceptance Criteria**:
  - [ ] `./scripts/release_smoke_non_docker.sh` exists and is the documented primary smoke script.
  - [ ] `./scripts/release_smoke_docker.sh` exists and verifies the fallback Docker path.
  - [ ] Both smoke scripts verify API health, web readiness, backend pipeline smoke, frontend unit tests, frontend build, and targeted Playwright flow.
  - [ ] Smoke output clearly identifies which path (`non-docker` or `docker-fallback`) is being verified.

  **QA Scenarios**:
  ```
  Scenario: Primary non-Docker smoke passes end-to-end
    Tool: Bash
    Steps: Run `./scripts/release_smoke_non_docker.sh` from repo root.
    Expected: Script exits 0 after verifying API/web readiness, backend e2e pytest, frontend unit tests, frontend build, and targeted Playwright task flow.
    Evidence: .sisyphus/evidence/task-7-non-docker-smoke.txt

  Scenario: Docker fallback smoke still passes
    Tool: Bash
    Steps: Run `./scripts/release_smoke_docker.sh` from repo root.
    Expected: Script exits 0 and still verifies container tool availability plus the same downstream backend/frontend checks.
    Evidence: .sisyphus/evidence/task-7-docker-smoke.txt
  ```

  **Commit**: YES | Message: `test(smoke): make non-docker primary and docker fallback explicit` | Files: `scripts/release_smoke_non_docker.sh`, `scripts/release_smoke_docker.sh`, `scripts/release_smoke.sh` (shim or redirect), related helper scripts

- [x] 8. Add detailed deployment guides and update top-level documentation indexes

  **What to do**: Write detailed deployment guides in English and Chinese that document the support matrix, primary/fallback workflows, WSL+ROCm install constraints, pip compatibility path, environment checks, and troubleshooting. Update README and operator manual/index files so the new guides are discoverable and Docker is clearly demoted to fallback status.
  **Must NOT do**: Do not turn this into cloud/prod deployment guidance; keep it scoped to the self-hosted/local environments implied by this repo.

  **Recommended Agent Profile**:
  - Category: `writing` - Reason: multi-document technical documentation with support-policy precision
  - Skills: [`roadmap-communicator`, `writing-plans`] - why needed: precise technical narrative and operational clarity
  - Omitted: [`seo-audit`] - why not needed: operational docs, not SEO work

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [] | Blocked By: [1, 3, 4, 6, 7]

  **References**:
  - Pattern: `README.md` - current top-level scope and dependency overview to update with new support matrix pointers
  - Pattern: `docs/operator-manual.md:16-24` - current service layout language to keep consistent
  - Pattern: `docs/operator-manual.md:48-84` - current startup and cookie guidance to refactor around non-Docker primary path
  - Pattern: `docs/operator-manual.md:105-128` - current GPU/media-tooling wording to replace with support-matrix language
  - Pattern: `docs/README.md` - documentation index structure to extend with deployment guides

  **Acceptance Criteria**:
  - [ ] `docs/deployment-guide.md` and `docs/deployment-guide.zh-CN.md` exist.
  - [ ] Guides include explicit sections for Linux+CUDA primary, WSL+ROCm full-function target, pip compatibility path, and Docker fallback.
  - [ ] Guides document startup commands, split-process commands, capability checks, warning semantics, and troubleshooting.
  - [ ] `README.md` and docs index files link to the deployment guides and no longer present Docker as the default startup path.

  **QA Scenarios**:
  ```
  Scenario: Deployment docs cover all named support paths
    Tool: Bash
    Steps: Run a content check (for example with Python or grep-equivalent via repo tests/scripts) that verifies both deployment guides contain section headers for Linux+CUDA, WSL+ROCm, pip compatibility, and Docker fallback.
    Expected: Both language variants contain all required sections and commands referenced by the implementation.
    Evidence: .sisyphus/evidence/task-8-doc-sections.txt

  Scenario: Documentation index points to the new primary path
    Tool: Bash
    Steps: Read `README.md`, `docs/README.md`, and `docs/operator-manual*.md` after changes and assert the deployment guide links exist and the primary startup examples reference non-Docker scripts before Docker fallback.
    Expected: Docs consistently point users to the uv-first workflow first and Docker fallback second.
    Evidence: .sisyphus/evidence/task-8-doc-index.txt
  ```

  **Commit**: YES | Message: `docs(deploy): add uv-first and wsl-rocm deployment guides` | Files: `docs/deployment-guide.md`, `docs/deployment-guide.zh-CN.md`, `README.md`, `docs/README.md`, `docs/README.zh-CN.md`, `docs/operator-manual*.md`

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [x] F1. Plan Compliance Audit — oracle
- [x] F2. Code Quality Review — unspecified-high
- [x] F3. Real Manual QA — unspecified-high (+ playwright if UI)
- [x] F4. Scope Fidelity Check — deep

## Commit Strategy
- Commit after each task; do not batch unrelated work.
- Recommended commit sequence:
  1. `feat(dev): add uv-first local startup scripts`
  2. `feat(runtime): add platform and capability detection`
  3. `feat(api): expose runtime capability status`
  4. `feat(worker): surface runtime capability warnings`
  5. `feat(web): surface runtime capability status`
  6. `build(python): export pip compatibility requirements`
  7. `test(smoke): make non-docker primary and docker fallback explicit`
  8. `docs(deploy): add uv-first and wsl-rocm deployment guides`

## Success Criteria
- A new contributor can start the full stack locally without Docker using documented uv+pnpm scripts.
- Backend capability status is visible through API, UI, and logs.
- Warning-only checks never block startup but make environment problems explicit.
- `backend/requirements.txt` is reproducible from the canonical dependency source and usable for pip installs.
- Docker remains functional only as a fallback path.
- Linux+CUDA remains non-regressed.
- WSL+ROCm is validated against at least one real task execution path, not only imports or device detection.
