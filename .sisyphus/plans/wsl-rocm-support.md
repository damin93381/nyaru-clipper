# Dedicated WSL+ROCm Support Plan

## TL;DR
> **Summary**: Add a dedicated WSL+ROCm installation, self-check, and smoke path while reusing the existing `dev_*` runtime entrypoints. Fix the real failure mode at dependency resolution time by separating CUDA and ROCm accelerator artifacts, then propagate one shared mismatch taxonomy through backend APIs, worker logs, UI, and docs.
> **Deliverables**:
> - Profile-specific backend accelerator artifacts for `linux-cuda` and `wsl-rocm`
> - Dedicated WSL install and doctor commands
> - Runtime capability payload with explicit torch build-family and mismatch issue codes
> - API / health / startup-log / worker-log / UI surfacing for WSL mismatch states
> - Dedicated WSL smoke script that fails unless the host is truly `wsl-rocm`
> - Rewritten deployment/operator docs for a dedicated WSL path using shared runtime entrypoints
> **Effort**: XL
> **Parallel**: YES - 2 waves
> **Critical Path**: Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6

## Context
### Original Request
- 按照 `docs/wsl-rocm-investigation.zh-CN.md` 的结论，制定方案改进当前项目，使其真正支持 WSL + ROCm。
- 用户要求：先充分搜索与分析；WSL 要有一套专门路径；方案尽量全覆盖。

### Interview Summary
- 当前根因已确认：WSL 内 ROCm 工具链能看到 AMD GPU，但项目 backend venv 安装成了 CUDA 版 PyTorch（`2.8.0+cu128`），因此 `torch.version.hip` 为空、`torch.cuda.is_available()` 为 `false`，项目正确落到 `cpu-only`。
- 用户明确要求：
  - WSL 必须有**专用安装 / 自检 / smoke 路径**。
  - 运行入口继续复用 `scripts/dev_api.sh`、`scripts/dev_worker.sh`、`scripts/dev_web.sh`、`scripts/dev_up.sh`。
  - 运行时策略为 **startup warning-only + dedicated self-check fail**。
  - 方案范围覆盖安装约束、文档、运行时诊断、验证流程、测试与 smoke 路径。

### Metis Review (gaps addressed)
- 解决了范围歧义：WSL 路径是**专用 install / doctor / smoke**，不是一套独立 runtime launcher family。
- 解决了失败策略歧义：API / worker 不阻断启动，但专用 WSL 自检必须在错误环境下明确失败。
- 解决了 artifact 策略歧义：不能继续共享一个会冻结 CUDA wheel 的 generic Linux artifact；必须把 accelerator family 的 install artifact 分开。
- 解决了验证不足：必须同时验证正确 WSL+ROCm 路径、错误 CUDA wheel 路径、以及 outside-WSL failure path，而不是只看 API 能否启动。

## Work Objectives
### Core Objective
让仓库具备一条**正式支持的 WSL+ROCm 专用路径**，在安装阶段避免默认 CUDA wheel 污染，在运行阶段提供明确、共享、可诊断的 mismatch 反馈，并通过专用 doctor/smoke 命令证明环境真的进入 `wsl-rocm`。

### Deliverables
- Dedicated WSL backend install script and profile-specific accelerator artifacts
- Dedicated WSL doctor/self-check command with strict pass/fail behavior
- Extended runtime capability schema with torch build-family + structured mismatch issues
- Shared API / health / startup-log / worker-log / UI mismatch surfacing
- Dedicated WSL smoke script
- Updated English + Chinese deployment/operator docs and doc indexes

### Definition of Done (verifiable conditions with commands)
- `bash -n scripts/install_backend_linux_cuda.sh scripts/install_backend_wsl_rocm.sh scripts/check_wsl_rocm.sh scripts/release_smoke_wsl_rocm.sh scripts/_backend_profile_common.sh` exits `0`.
- `./scripts/install_backend_wsl_rocm.sh --dry-run` exits `0` and prints the exact WSL+ROCm artifact path instead of generic `uv sync --project backend --frozen` only.
- `./scripts/check_wsl_rocm.sh` exits nonzero with an explicit mismatch reason when run outside WSL or with a CUDA-built torch.
- On a healthy WSL ROCm host, `./scripts/check_wsl_rocm.sh` exits `0` and prints a success marker such as `WSL_ROCM_READY`.
- `uv run --project backend pytest backend/tests/test_runtime_capabilities.py backend/tests/test_runtime_api.py backend/tests/test_worker_runtime_warnings.py backend/tests/test_runtime_doctor.py backend/tests/test_requirements_export.py backend/tests/test_startup_local_dev.py -q` passes.
- `pnpm --dir web exec vitest run src/components/__tests__/EnvironmentStatusCard.test.tsx` passes.
- `./scripts/release_smoke_wsl_rocm.sh` exits `0` only on a true `wsl-rocm` environment and exits nonzero with an explicit unsupported/mismatch message otherwise.
- The WSL section in `docs/deployment-guide*.md` uses the dedicated WSL install / doctor / smoke path and explicitly reuses `scripts/dev_api.sh`, `scripts/dev_worker.sh`, `scripts/dev_web.sh`, and `scripts/dev_up.sh` as the runtime entrypoints.

### Must Have
- Dedicated install artifacts for `linux-cuda` and `wsl-rocm`; no more one-size-fits-all accelerator artifact.
- Dedicated WSL doctor command that fails outside WSL or on wrong torch family.
- Runtime payload must distinguish generic `cpu-only` from explicit WSL mismatch states.
- Health, runtime API, startup logs, worker stage logs, and UI all use the same mismatch vocabulary.
- Dedicated WSL smoke path must call the doctor before stack readiness checks.
- Documentation must treat WSL+ROCm as a standalone supported path with exact commands and expected outputs.

### Must NOT Have
- Must NOT create a second runtime launcher family parallel to `dev_api.sh` / `dev_worker.sh` / `dev_web.sh` / `dev_up.sh`.
- Must NOT auto-install, auto-repair, or mutate dependencies during app startup.
- Must NOT keep one shared accelerator lock/export artifact that can freeze CUDA wheels for WSL.
- Must NOT broaden scope to native Linux ROCm, Windows-native GPU, or Docker ROCm support.
- Must NOT switch model device strings to `rocm`; ROCm PyTorch continues to use `cuda`.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: tests-after using existing `pytest`, `Vitest`, bash-based doctor/smoke scripts, and shell syntax checks
- QA policy: Every task includes exact happy-path + failure-path scenarios with binary pass/fail expectations
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.{ext}`

## Execution Strategy
### Parallel Execution Waves
> Target: 5-8 tasks per wave. <3 per wave (except final) = under-splitting.
> Extract shared dependencies as Wave-1 tasks for max parallelism.

Wave 1: install-path and runtime-classification foundation
- Task 1: Split accelerator artifacts and add dedicated install wrappers
- Task 2: Extend runtime classification with build-family + mismatch taxonomy
- Task 3: Add dedicated WSL doctor/self-check command

Wave 2: propagation, smoke, and docs
- Task 4: Surface mismatch diagnostics through API, startup logs, worker logs, and UI
- Task 5: Add dedicated WSL smoke path and shared verification helpers
- Task 6: Rewrite deployment/operator docs around the dedicated WSL path

### Dependency Matrix (full, all tasks)
- Task 1 blocks Tasks 3, 5, and 6
- Task 2 blocks Tasks 3, 4, 5, and 6
- Task 3 blocks Tasks 5 and 6
- Task 4 depends on Task 2 and informs Task 6
- Task 5 depends on Tasks 1, 2, and 3
- Task 6 depends on Tasks 1, 2, 3, 4, and 5

### Agent Dispatch Summary (wave → task count → categories)
- Wave 1 → 3 tasks → `unspecified-high`, `senior-devops`, `senior-backend`
- Wave 2 → 3 tasks → `unspecified-high`, `visual-engineering`, `writing`

## TODOs
> Implementation + Test = ONE task. Never separate.
> EVERY task MUST have: Agent Profile + Parallelization + QA Scenarios.

- [x] 1. Split accelerator artifacts and add dedicated install wrappers

  **What to do**: Move accelerator-bound packages out of the generic backend artifact path so `backend/requirements.txt` stops freezing CUDA-family wheels for every Linux host. Introduce explicit, checked-in profile artifacts for `linux-cuda` and `wsl-rocm`, plus dedicated install wrappers that apply the correct artifact while keeping runtime entrypoints unchanged.
  **Must NOT do**: Do not keep plain `torch` inside the generic exported artifact path; do not make `dev_up.sh` responsible for dependency family selection; do not create WSL-specific `dev_*` launchers.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: multi-file dependency-layout and script-surface change with cross-platform impact
  - Skills: [`senior-devops`] - why needed: profile-specific install orchestration, artifact hygiene, shell/script contracts
  - Omitted: [`docker-development`] - why not needed: Docker remains fallback only and is not the WSL support surface

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [3, 5, 6] | Blocked By: []

  **References** (executor has NO interview context - be exhaustive):
  - Pattern: `backend/pyproject.toml:7-18` - current generic dependency graph includes plain `torch` and `whisperx`
  - Pattern: `backend/requirements.txt:1-70` - current exported artifact already freezes `nvidia-*` CUDA packages on Linux
  - Pattern: `scripts/export_backend_requirements.sh:60-119` - existing generated-artifact flow and stale-check behavior to extend
  - Test: `backend/tests/test_requirements_export.py:21-50` - current export regression coverage pattern
  - Pattern: `scripts/_dev_common.sh:8-30` - current helper-script style for shared shell functions and environment setup
  - External: https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.2/docs/install/installrad/wsl/install-pytorch.html - WSL ROCm uses explicit ROCm wheel installation, not generic PyPI torch
  - External: https://pytorch.org/get-started/locally/ - official install matrix distinguishes ROCm from default pip install flows

  **Acceptance Criteria** (agent-executable only):
  - [ ] `backend/requirements.txt` no longer contains `torch`, `torchaudio`, `torchvision`, `whisperx`, `faster-whisper`, `ctranslate2`, or any `nvidia-*` accelerator package.
  - [ ] New checked-in profile artifacts exist at `backend/requirements-linux-cuda.txt` and `backend/requirements-wsl-rocm.txt`.
  - [ ] `backend/requirements-linux-cuda.txt` contains CUDA-family runtime packages and no ROCm wheel URL.
  - [ ] `backend/requirements-wsl-rocm.txt` contains ROCm-specific torch-family installation lines and no `nvidia-*` packages.
  - [ ] `scripts/install_backend_linux_cuda.sh` and `scripts/install_backend_wsl_rocm.sh` exist and support `--dry-run` without mutating the environment.
  - [ ] `./scripts/export_backend_requirements.sh --check` still validates the generic artifact, and pytest coverage validates the new profile artifact invariants.

  **QA Scenarios** (MANDATORY - task incomplete without these):
  ```
  Scenario: Generic backend artifact is accelerator-neutral
    Tool: Bash
    Steps: Run `./scripts/export_backend_requirements.sh --check` and `uv run --project backend pytest backend/tests/test_requirements_export.py -q`.
    Expected: Export check passes; pytest asserts generic requirements are stale-safe and accelerator-neutral while profile-specific artifacts remain present.
    Evidence: .sisyphus/evidence/task-1-artifacts.txt

  Scenario: WSL install wrapper stays on the dedicated path
    Tool: Bash
    Steps: Run `./scripts/install_backend_wsl_rocm.sh --dry-run`.
    Expected: Exit code is 0; output mentions `backend/requirements-wsl-rocm.txt` and does not present a plain `uv sync --project backend --frozen`-only path as sufficient.
    Evidence: .sisyphus/evidence/task-1-wsl-install-dry-run.txt
  ```

  **Commit**: YES | Message: `feat(runtime): split backend accelerator install artifacts` | Files: `backend/pyproject.toml`, `backend/requirements.txt`, `backend/requirements-linux-cuda.txt`, `backend/requirements-wsl-rocm.txt`, `scripts/export_backend_requirements.sh`, `scripts/_backend_profile_common.sh`, `scripts/install_backend_linux_cuda.sh`, `scripts/install_backend_wsl_rocm.sh`, `backend/tests/test_requirements_export.py`

- [x] 2. Extend runtime classification with build-family and mismatch taxonomy

  **What to do**: Keep one shared runtime-classification service, but enrich it so WSL mismatch states are first-class rather than hidden behind generic `cpu-only`. Add explicit torch build-family reporting, optional device-name reporting, and structured issue codes so downstream API/UI/worker surfaces can identify “CUDA wheel installed on WSL target” vs “HIP build installed but no device” vs generic CPU fallback.
  **Must NOT do**: Do not create a second WSL runtime subsystem; do not change ASR/translation device strings away from `cuda`; do not make startup blocking.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: central runtime contract change consumed across backend and frontend
  - Skills: [`senior-backend`, `senior-devops`] - why needed: runtime fact modeling, status taxonomy, platform diagnostics
  - Omitted: [`senior-frontend`] - why not needed: this task defines the backend contract only

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [3, 4, 5, 6] | Blocked By: []

  **References**:
  - Pattern: `backend/app/services/runtime_profile.py:53-139` - current accelerator/profile inference
  - Pattern: `backend/app/services/capability_checks.py:18-119` - current warning/status aggregation and core dependency checks
  - Pattern: `backend/app/services/runtime_capabilities.py:8-23` - cached summary contract
  - Pattern: `backend/app/settings.py:16-27` - `cuda` remains the configured model device token and must stay valid for ROCm
  - Pattern: `backend/app/services/asr_whisperx.py:57-82` - WhisperX currently consumes `settings.whisperx_device` directly
  - Pattern: `backend/app/services/translation_provider.py:43-61` - translation provider currently consumes `settings.translation_device` directly
  - Test: `backend/tests/test_runtime_capabilities.py:55-299` - existing runtime profile / warning contract tests to expand
  - External: https://github.com/ROCm/pytorch/blob/9f8ad3e96fa9a397cf7e24cf505b35c019aef903/docs/source/notes/hip.rst - ROCm still uses `torch.cuda.*` and `torch.version.hip`

  **Acceptance Criteria**:
  - [ ] Runtime payload remains JSON-serializable and still includes `status`, `detected_profile`, `platform`, `accelerator`, `dependencies`, and `warnings`.
  - [ ] `accelerator` gains explicit build-family metadata (for example `torch_build_family`) and device-name metadata when available.
  - [ ] Payload gains structured issue entries (for example `issues`) with at least these codes: `wrong_torch_build_cuda_on_wsl`, `cpu_only_torch_on_wsl`, `hip_build_no_device`.
  - [ ] A WSL host with CUDA-built torch surfaces `status: error` plus `wrong_torch_build_cuda_on_wsl` instead of only a generic `cpu-only` warning.
  - [ ] Existing healthy classifications remain valid: non-WSL CUDA stays `linux-cuda`; WSL HIP + available device stays `wsl-rocm`.
  - [ ] `uv run --project backend pytest backend/tests/test_runtime_capabilities.py -q` passes with deterministic coverage of the new mismatch cases.

  **QA Scenarios**:
  ```
  Scenario: Runtime taxonomy distinguishes WSL mismatch states
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_runtime_capabilities.py -q`.
    Expected: Tests assert exact issue codes and status transitions for WSL+ROCm happy path, WSL+CUDA wheel mismatch, WSL+CPU-only torch, HIP build with no device, and non-WSL Linux+CUDA.
    Evidence: .sisyphus/evidence/task-2-runtime-taxonomy.txt

  Scenario: Shared execution semantics remain unchanged for model device strings
    Tool: Bash
    Steps: Search the modified backend tree for `device="rocm"` or equivalent ROCm-only device token usage in production code.
    Expected: No production path switches WhisperX or translation provider away from the existing `cuda` device token.
    Evidence: .sisyphus/evidence/task-2-device-token-audit.txt
  ```

  **Commit**: YES | Message: `feat(runtime): add explicit WSL ROCm mismatch classification` | Files: `backend/app/services/runtime_profile.py`, `backend/app/services/capability_checks.py`, `backend/app/services/runtime_capabilities.py`, optional new helper such as `backend/app/services/runtime_diagnostics.py`, `backend/tests/test_runtime_capabilities.py`

- [x] 3. Add dedicated WSL doctor/self-check command

  **What to do**: Introduce one dedicated WSL doctor command that is strict by design. It must validate WSL detection, torch build family, HIP visibility, device availability, and key runtime imports, and it must fail with explicit remediation text if the environment is outside WSL or has the wrong torch family. Keep this command separate from app startup so startup remains warning-only.
  **Must NOT do**: Do not auto-install wheels, do not mutate the environment, and do not depend on the API already running.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: CLI/doctor behavior with strict exit-code semantics and detailed diagnostics
  - Skills: [`senior-backend`, `systematic-debugging`] - why needed: root-cause-oriented self-check and precise failure classification
  - Omitted: [`senior-frontend`] - why not needed: no UI work in this task

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [5, 6] | Blocked By: [1, 2]

  **References**:
  - Pattern: `backend/app/services/runtime_profile.py:102-139` - current runtime fact gathering to reuse instead of re-implementing detection
  - Pattern: `backend/app/services/capability_checks.py:97-119` - current capability payload assembly to reuse as doctor input
  - Pattern: `scripts/_dev_common.sh:8-30` - shell helper style for shared script logic
  - Test: `backend/tests/test_runtime_capabilities.py:86-130` - current WSL+ROCm fixture style for backend-side validation
  - External: https://github.com/aqlaboratory/openfold-3/blob/cc8bf9dd3f162fed45cc1189a130877996b425d3/openfold3/entry_points/validate_rocm.py#L36-L120 - high-signal ROCm validator pattern
  - External: `docs/wsl-rocm-investigation.zh-CN.md:217-230` - expected WSL verification commands and target `wsl-rocm` outcome

  **Acceptance Criteria**:
  - [ ] A dedicated wrapper exists at `scripts/check_wsl_rocm.sh` and calls a backend-owned Python doctor entrypoint.
  - [ ] Running `./scripts/check_wsl_rocm.sh` outside WSL exits nonzero with an explicit unsupported message.
  - [ ] Running `./scripts/check_wsl_rocm.sh` on WSL with CUDA-built torch exits nonzero and mentions `wrong_torch_build_cuda_on_wsl` or equivalent remediation text.
  - [ ] Running `./scripts/check_wsl_rocm.sh` on a healthy WSL ROCm host exits `0` and prints a success marker such as `WSL_ROCM_READY`.
  - [ ] Doctor output checks `torch.version.hip`, `torch.cuda.is_available()`, `torch.cuda.device_count()`, `torch.cuda.get_device_name(0)` when device count is nonzero, and key Python/runtime imports.
  - [ ] `uv run --project backend pytest backend/tests/test_runtime_doctor.py -q` passes.

  **QA Scenarios**:
  ```
  Scenario: Doctor fails on unsupported or mismatched environment
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_runtime_doctor.py -q`.
    Expected: Tests assert exact exit-code semantics and mismatch messages for outside-WSL, CUDA-wheel-on-WSL, CPU-only torch, and HIP-without-device cases.
    Evidence: .sisyphus/evidence/task-3-runtime-doctor.txt

  Scenario: Wrapper script is stable and shell-valid
    Tool: Bash
    Steps: Run `bash -n scripts/check_wsl_rocm.sh`.
    Expected: Exit code is 0 and no shell syntax errors are reported.
    Evidence: .sisyphus/evidence/task-3-check-script-syntax.txt
  ```

  **Commit**: YES | Message: `feat(runtime): add dedicated WSL ROCm doctor command` | Files: `scripts/check_wsl_rocm.sh`, backend doctor entrypoint such as `backend/app/runtime_doctor.py`, `backend/tests/test_runtime_doctor.py`, optional shared helper updates in `scripts/_dev_common.sh`

- [x] 4. Surface mismatch diagnostics through API, startup logs, worker logs, and UI

  **What to do**: Extend the existing runtime surfaces so operators see the exact mismatch rather than a vague degraded state. Keep the current endpoints and UI card, but teach them to expose issue codes, build-family data, and WSL-specific corrective messaging while remaining non-blocking at startup.
  **Must NOT do**: Do not remove `warnings`; do not break `/api/health`; do not make the UI depend on the doctor command being run first.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: mixed backend contract propagation + user-facing UI state presentation
  - Skills: [`senior-frontend`, `senior-backend`] - why needed: shared payload typing plus status-card rendering
  - Omitted: [`senior-architect`] - why not needed: architecture and issue taxonomy are already fixed by Tasks 2 and 3

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [6] | Blocked By: [2]

  **References**:
  - Pattern: `backend/app/api/routes/runtime.py:7-12` - full runtime payload endpoint
  - Pattern: `backend/app/api/routes/health.py:12-20` - compact summary contract that must stay backward-compatible
  - Pattern: `backend/app/main.py:18-33` - startup summary log shape
  - Pattern: `backend/app/worker.py:24-43,113-130` - worker preflight warning surfacing path
  - Pattern: `web/src/lib/types.ts:100-153` - shared frontend runtime type contract and full-function profile helper
  - Pattern: `web/src/components/EnvironmentStatusCard.tsx:44-148` - current status/warning rendering behavior
  - Pattern: `web/src/components/AppShell.tsx:7-36` - existing runtime query integration point
  - Test: `backend/tests/test_runtime_api.py:24-144` - health/runtime/startup-log contract tests
  - Test: `backend/tests/test_worker_runtime_warnings.py:38-203` - worker preflight warning summary tests
  - Test: `web/src/components/__tests__/EnvironmentStatusCard.test.tsx:6-90` - environment-status UI behavior tests

  **Acceptance Criteria**:
  - [ ] `/api/runtime/capabilities` returns the enriched payload verbatim, including structured mismatch issues.
  - [ ] `/api/health` remains HTTP `200` and backward-compatible, but its compact `runtime_capabilities` summary includes enough mismatch detail to distinguish WSL CUDA-wheel errors from generic CPU fallback (for example via `issue_codes`).
  - [ ] Startup logs emit one structured record containing profile, status, warnings, and issue codes.
  - [ ] Worker preflight logs include the structured mismatch payload, not just generic warnings.
  - [ ] `EnvironmentStatusCard` renders a targeted WSL+ROCm mismatch message when `wrong_torch_build_cuda_on_wsl` is present and continues to show the healthy `wsl-rocm` state when the profile is satisfied.
  - [ ] `uv run --project backend pytest backend/tests/test_runtime_api.py backend/tests/test_worker_runtime_warnings.py -q` and `pnpm --dir web exec vitest run src/components/__tests__/EnvironmentStatusCard.test.tsx` pass.

  **QA Scenarios**:
  ```
  Scenario: API and startup logs expose explicit mismatch metadata
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_runtime_api.py -q`.
    Expected: Tests assert `/api/health`, `/api/runtime/capabilities`, and startup log payloads preserve compatibility while surfacing issue codes and richer accelerator metadata.
    Evidence: .sisyphus/evidence/task-4-runtime-api.txt

  Scenario: Worker and UI show the same mismatch semantics
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_worker_runtime_warnings.py -q` and `pnpm --dir web exec vitest run src/components/__tests__/EnvironmentStatusCard.test.tsx`.
    Expected: Worker preflight summaries include the new issue taxonomy; the UI renders the same mismatch as a user-facing action state.
    Evidence: .sisyphus/evidence/task-4-worker-ui.txt
  ```

  **Commit**: YES | Message: `feat(runtime): surface WSL ROCm mismatch diagnostics` | Files: `backend/app/api/routes/runtime.py`, `backend/app/api/routes/health.py`, `backend/app/main.py`, `backend/app/worker.py`, `web/src/lib/types.ts`, `web/src/components/EnvironmentStatusCard.tsx`, optionally `web/src/components/AppShell.tsx`, associated tests

- [x] 5. Add dedicated WSL smoke path and shared verification helpers

  **What to do**: Add a dedicated release-smoke path for WSL+ROCm that first runs the strict doctor command, then starts the normal local stack via shared `dev_*` entrypoints, verifies runtime profile readiness, and runs the existing downstream smoke suite. Keep the generic non-Docker smoke path intact.
  **Must NOT do**: Do not make the generic `release_smoke_non_docker.sh` depend on WSL; do not let the dedicated WSL smoke script silently skip the doctor or pass on a mismatched CUDA wheel.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: shell smoke orchestration with platform-specific fail-fast behavior
  - Skills: [`senior-devops`] - why needed: smoke-path composition, helper reuse, shell verification
  - Omitted: [`playwright-pro`] - why not needed: existing downstream smoke suite already invokes Playwright via shared helpers

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [6] | Blocked By: [1, 2, 3]

  **References**:
  - Pattern: `scripts/_release_smoke_common.sh:30-83` - shared smoke verification helpers and downstream suite integration
  - Pattern: `scripts/release_smoke_non_docker.sh:10-47` - current host-path smoke orchestration via `dev_up.sh`
  - Pattern: `scripts/_dev_common.sh:44-77` - current wait/poll helper to reuse for WSL smoke readiness checks
  - Pattern: `backend/tests/test_startup_local_dev.py:9-31` - current startup/health import contract
  - External: `docs/wsl-rocm-investigation.zh-CN.md:217-230` - explicit target verification commands for `torch.version.hip`, `torch.cuda.is_available()`, and `wsl-rocm`

  **Acceptance Criteria**:
  - [ ] `scripts/release_smoke_wsl_rocm.sh` exists and calls `scripts/check_wsl_rocm.sh` before stack startup.
  - [ ] Running `scripts/release_smoke_wsl_rocm.sh` outside WSL exits nonzero with an explicit unsupported message before `dev_up.sh` is started.
  - [ ] Running the WSL smoke script on a mismatched CUDA-wheel environment exits nonzero before downstream smoke tests run.
  - [ ] Running the WSL smoke script on a healthy WSL ROCm host starts the shared stack and verifies `runtime_capabilities.detected_profile == "wsl-rocm"` before continuing into the existing downstream smoke suite.
  - [ ] Generic non-Docker smoke remains valid for non-WSL hosts.

  **QA Scenarios**:
  ```
  Scenario: Dedicated WSL smoke path fails fast on unsupported host
    Tool: Bash
    Steps: Run `./scripts/release_smoke_wsl_rocm.sh` on a non-WSL or intentionally mismatched environment.
    Expected: Exit code is nonzero; output names the explicit unsupported or mismatch reason; downstream smoke suite is not invoked.
    Evidence: .sisyphus/evidence/task-5-wsl-smoke-fail.txt

  Scenario: Shared non-Docker smoke path remains intact
    Tool: Bash
    Steps: Run `bash -n scripts/release_smoke_wsl_rocm.sh scripts/release_smoke_non_docker.sh scripts/_release_smoke_common.sh` and execute `uv run --project backend pytest backend/tests/test_startup_local_dev.py -q`.
    Expected: Shell syntax checks pass; startup-local-dev contract remains green; dedicated WSL path is additive rather than destructive.
    Evidence: .sisyphus/evidence/task-5-smoke-contract.txt
  ```

  **Commit**: YES | Message: `feat(smoke): add dedicated WSL ROCm validation path` | Files: `scripts/release_smoke_wsl_rocm.sh`, `scripts/_release_smoke_common.sh`, optional helper changes in `scripts/_dev_common.sh`, `backend/tests/test_startup_local_dev.py`

- [x] 6. Rewrite deployment and operator docs around the dedicated WSL path

  **What to do**: Rewrite the WSL sections so they no longer tell users to rely on the generic `uv sync --project backend --frozen` path alone. Document the dedicated WSL install script, doctor command, shared runtime entrypoints, dedicated WSL smoke script, supported scope, expected outputs, and the exact meaning of mismatch states. Update operator docs to stop assuming a NVIDIA-only host.
  **Must NOT do**: Do not document a separate WSL runtime launcher family; do not leave the old generic WSL instructions in place; do not claim support beyond WSL2 Ubuntu 22.04/24.04 + official AMD ROCm path.

  **Recommended Agent Profile**:
  - Category: `writing` - Reason: bilingual deployment/operator documentation rewrite with technical precision
  - Skills: [`roadmap-communicator`] - why needed: clear operator-facing explanation of supported paths and mismatch states
  - Omitted: [`copywriting`] - why not needed: this is technical operations documentation, not marketing copy

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [] | Blocked By: [1, 2, 3, 4, 5]

  **References**:
  - Pattern: `docs/deployment-guide.zh-CN.md:111-157` - current WSL section that still points users at the generic install flow
  - Pattern: `docs/deployment-guide.zh-CN.md:159-197` - current pip compatibility section and its cautionary language to align with the new artifact model
  - Pattern: `docs/operator-manual.zh-CN.md:50-72` - current startup commands section to keep shared runtime entrypoints consistent
  - Pattern: `docs/operator-manual.zh-CN.md:123-140` - current model/device defaults, including `cuda` defaults that remain valid for ROCm
  - Pattern: `docs/operator-manual.zh-CN.md:179-189` - current runtime capability visibility section to extend with doctor/self-check guidance
  - Pattern: `docs/operator-manual.zh-CN.md:138-148` - current NVIDIA-only assumption that must be removed or rewritten
  - Pattern: `docs/README.md:10-23` and `docs/README.zh-CN.md:10-18` - doc index entries that must point to the updated WSL support path
  - Pattern: `docs/wsl-rocm-investigation.zh-CN.md:20-248` - investigation note containing the root-cause narrative and exact mismatch explanation
  - External: https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/wsl/howto_wsl.html - authoritative WSL ROCm setup path

  **Acceptance Criteria**:
  - [ ] `docs/deployment-guide.md` and `docs/deployment-guide.zh-CN.md` each contain a dedicated WSL+ROCm install section with exact commands for install, doctor, runtime startup, and WSL smoke.
  - [ ] Both deployment guides explicitly state that WSL uses dedicated install / self-check / smoke commands but still reuses `dev_api.sh`, `dev_worker.sh`, `dev_web.sh`, and `dev_up.sh` for runtime startup.
  - [ ] `docs/operator-manual.md` and `docs/operator-manual.zh-CN.md` no longer describe the MVP as NVIDIA-only; they explain mismatch visibility through API/UI/logs plus the dedicated doctor command.
  - [ ] `docs/README.md` and `docs/README.zh-CN.md` point readers to the dedicated WSL support path.

  **QA Scenarios**:
  ```
  Scenario: WSL docs point to the dedicated path rather than the generic install path
    Tool: Bash
    Steps: Read the updated deployment and operator docs and grep for the dedicated WSL install / doctor / smoke commands.
    Expected: Both language sets document the dedicated WSL path and explicitly describe the shared runtime entrypoints; the old WSL section no longer implies generic `uv sync --project backend --frozen` is sufficient by itself.
    Evidence: .sisyphus/evidence/task-6-docs-audit.txt

  Scenario: Documentation indexes expose the new support path
    Tool: Bash
    Steps: Read `docs/README.md` and `docs/README.zh-CN.md` after the doc rewrite.
    Expected: Both indexes contain a discoverable entry for the dedicated WSL+ROCm support documentation.
    Evidence: .sisyphus/evidence/task-6-doc-index.txt
  ```

  **Commit**: YES | Message: `docs(deploy): add dedicated WSL ROCm support path` | Files: `docs/deployment-guide.md`, `docs/deployment-guide.zh-CN.md`, `docs/operator-manual.md`, `docs/operator-manual.zh-CN.md`, `docs/README.md`, `docs/README.zh-CN.md`, optional updates to `docs/wsl-rocm-investigation.zh-CN.md`

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [ ] F1. Plan Compliance Audit — oracle
- [ ] F2. Code Quality Review — unspecified-high
- [ ] F3. Real Manual QA — unspecified-high (+ playwright if UI)
- [ ] F4. Scope Fidelity Check — deep

## Commit Strategy
- Task 1: `feat(runtime): split backend accelerator install artifacts`
- Task 2: `feat(runtime): add explicit WSL ROCm mismatch classification`
- Task 3: `feat(runtime): add dedicated WSL ROCm doctor command`
- Task 4: `feat(runtime): surface WSL ROCm mismatch diagnostics`
- Task 5: `feat(smoke): add dedicated WSL ROCm validation path`
- Task 6: `docs(deploy): add dedicated WSL ROCm support path`
- Final polish after verification only if required by review findings; otherwise no extra commit.

## Success Criteria
- WSL support is no longer a doc-only branch under generic Linux install guidance; it is a dedicated, repo-supported path.
- Installing the wrong CUDA wheel family for WSL becomes structurally harder at install time and unmistakable at runtime.
- Operators can distinguish `wrong_torch_build_cuda_on_wsl`, `cpu_only_torch_on_wsl`, and `hip_build_no_device` without reading source code.
- The shared runtime entrypoints remain the only way to launch the stack locally.
- Dedicated WSL doctor and smoke commands provide a binary answer to “is this host actually ready for `wsl-rocm`?”.
