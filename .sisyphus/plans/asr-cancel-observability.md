# ASR Cancellation and Observability Update

## TL;DR
> **Summary**: Rework the ASR stage from an in-process WhisperX call into a tracked subprocess with structured phase progress, heartbeat updates, graceful cancel, and force-kill support, while preserving current transcription/alignment quality and deferring CPU/GPU tuning.
> **Deliverables**:
> - Backend ASR subprocess runner with structured phase/timing events
> - Parent-owned heartbeat/cancel/force-kill orchestration for `asr`
> - Persisted `execution_progress` surfaced in task detail API
> - Frontend Task Detail progress/timing UI for active ASR work
> - Regression coverage for cancel, stale recovery, and progress surfacing
> - Operator/deployment docs for the new ASR lifecycle semantics
> **Effort**: Large
> **Parallel**: YES - 3 waves
> **Critical Path**: 1 → 2 → 3 → 4 → 5 → 6

## Context
### Original Request
- Combine the first two ASR updates: true ASR cancellation/interruption and ASR observability/timing visibility.
- Do **not** prioritize CPU/GPU investigation in this phase.
- Do **not** introduce quality-reducing speed optimizations in this phase.
- Priority chosen by user: **先做可观测+测速**.

### Interview Summary
- Current `asr` cancellation only becomes effective at stage boundaries.
- Current ASR logging is too sparse to distinguish “running normally” from “stuck”.
- User wants the two updates added now; speed tuning will come later and should be enabled by better instrumentation, not by changing model quality.
- User confirmed the combined direction and approved moving forward.

### Metis Review (gaps addressed)
- Resolved the missing decision on execution boundary: ASR becomes a dedicated subprocess, not an in-process cooperative wrapper.
- Resolved the missing decision on progress transport: child emits structured JSONL progress events; parent remains sole DB-state owner.
- Added explicit guardrails against scope creep into CPU/GPU tuning, model swaps, or alignment quality changes.
- Added explicit edge-case handling for cancel during `model_load`, stale ASR process-group cleanup, and partial-result publication rules.

## Work Objectives
### Core Objective
Implement a first-phase ASR architecture that supports **real cancellation/interruption semantics** and **operator-visible phase/timing progress** without lowering transcription or alignment quality.

### Deliverables
- New ASR child-runner path for `model_load`, `vad`, `transcribe`, `align`, and `persist`.
- New persisted ASR `execution_progress` state for active tasks.
- Parent-side tracked subprocess orchestration for ASR, including heartbeat updates and process-group cleanup.
- Updated task detail API and frontend rendering for ASR phase/timing/cancel-pending status.
- Regression coverage for:
  - cancel during ASR
  - force-kill during ASR
  - stale ASR process-group recovery
  - progress payload serialization and frontend rendering

### Definition of Done (verifiable conditions with commands)
- Backend tests covering ASR cancel/progress/stale recovery pass:
  - `uv run --directory backend python -m pytest tests/test_worker_cancellation.py tests/test_task_control_api.py tests/test_task_runner.py tests/test_asr_whisperx.py -q`
- Frontend task detail tests pass:
  - `pnpm --dir web exec vitest run src/pages/__tests__/TaskDetailPage.test.tsx src/lib/__tests__/api.test.ts src/test/smoke.test.tsx`
- Frontend build passes:
  - `pnpm --dir web build`
- Live task detail shows `execution_progress.current_phase` and phase timings during ASR.
- Cancelling an active ASR task changes task detail to `cancel_requested`, sends a graceful stop to the ASR subprocess, and reaches terminal `cancelled` without remaining permanently in `asr`.

### Must Have
- Parent worker is the only writer of task/job/stage/control terminal state.
- Child ASR runner emits structured phase events and writes outputs/manifests only under the task work directory.
- `asr` becomes killable **only when** a tracked process group is active.
- Existing `ingest` and `media_prep` cancellation semantics remain unchanged.
- No reduction in default WhisperX model, alignment model, compute type, or subtitle alignment fidelity in this phase.

### Must NOT Have (guardrails, AI slop patterns, scope boundaries)
- Must NOT change `whisperx_model_name`, `whisperx_compute_type`, `whisperx_batch_size`, or alignment defaults as part of this phase.
- Must NOT remove alignment, VAD, or other quality-preserving steps.
- Must NOT overload current free-text `stage.summary` to carry the full structured progress contract.
- Must NOT let the child subprocess write DB state directly.
- Must NOT broaden force-kill semantics to unrelated stages.
- Must NOT introduce a general-purpose tracing platform or metrics backend in this phase.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: **tests-after** using existing pytest + vitest stack; add focused regressions before any behavioral change in the touched area.
- QA policy: Every task below includes agent-executed scenarios.
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.{ext}`

## Execution Strategy
### Parallel Execution Waves
> Target: 5-8 tasks per wave. <3 per wave (except final) = under-splitting.
> Extract shared dependencies as Wave-1 tasks for max parallelism.

Wave 1: backend foundations
- Task 1: progress persistence + API contract
- Task 2: ASR child-runner protocol and manifest contract
- Task 3: generic tracked streaming subprocess helper for structured progress

Wave 2: backend orchestration and recovery
- Task 4: wire `asr` into parent-owned subprocess execution
- Task 5: extend cancellation / stale recovery / force-kill semantics for `asr`

Wave 3: product surface and docs
- Task 6: frontend task detail progress/timing UI
- Task 7: focused backend/frontend regressions and integration assertions
- Task 8: operator/deployment/user-facing docs for new ASR lifecycle semantics

### Dependency Matrix (full, all tasks)
| Task | Depends On | Blocks |
|---|---|---|
| 1 | none | 4, 6, 7 |
| 2 | none | 4, 7 |
| 3 | none | 4, 5, 7 |
| 4 | 1, 2, 3 | 5, 6, 7, 8 |
| 5 | 3, 4 | 7, 8 |
| 6 | 1, 4 | 7 |
| 7 | 1, 2, 3, 4, 5, 6 | 8, Final Verification |
| 8 | 4, 5, 6, 7 | Final Verification |

### Agent Dispatch Summary
| Wave | Task Count | Categories |
|---|---:|---|
| 1 | 3 | unspecified-high, deep |
| 2 | 2 | unspecified-high |
| 3 | 3 | unspecified-high, visual-engineering, writing |

## TODOs
> Implementation + Test = ONE task. Never separate.
> EVERY task MUST have: Agent Profile + Parallelization + QA Scenarios.

- [x] 1. Add persisted ASR execution-progress contract

  **What to do**: Introduce a new repo-safe persistence layer for active execution progress, using a **new table** rather than altering existing tables. Add a new backend model named `TaskExecutionProgress` keyed by `task_id`, with these exact persisted fields: `task_id`, `stage_name`, `current_phase`, `phase_index`, `phase_count`, `latest_message`, `phase_started_at`, `heartbeat_at`, `phase_timings_json`, and `updated_at`. Extend `GET /api/tasks/{task_id}` to include a single `execution_progress` object with this exact shape when relevant:
  `{"stage_name":"asr","current_phase":"transcribe","phase_index":3,"phase_count":5,"phase_started_at":"ISO-8601","heartbeat_at":"ISO-8601","latest_message":"...","phases":[{"name":"model_load","status":"success","elapsed_ms":1234},{"name":"vad","status":"success","elapsed_ms":4567},{"name":"transcribe","status":"running","elapsed_ms":8901},{"name":"align","status":"pending","elapsed_ms":null},{"name":"persist","status":"pending","elapsed_ms":null}]}`.
  Keep `execution_progress` absent or `null` for tasks with no active tracked ASR execution.
  **Must NOT do**: Do not add columns to existing SQLModel tables; this repo does not have schema migrations. Do not put structured progress into `stage.summary`.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: touches persistence, serialization, and compatibility rules.
  - Skills: [`senior-backend`] - reason: SQLModel contract + API serialization.
  - Omitted: [`senior-frontend`] - reason: no UI changes in this task.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: 4, 6, 7 | Blocked By: none

  **References**:
  - Pattern: `backend/app/models.py:72-80` - current execution control state lives in a dedicated table; follow the same “new table, no migration” pattern.
  - Pattern: `backend/app/repositories/tasks.py:127-151` - task detail already overlays control-driven status into API shape.
  - Pattern: `backend/app/repositories/tasks.py:295-311` - current log summary surface is intentionally lossy; do not rely on it for structured progress.
  - API/Type: `web/src/lib/types.ts:211-222` - current `RuntimeCapabilities` is fully typed; mirror that approach for a typed `execution_progress` contract.
  - Test: `backend/tests/test_runtime_api.py:125-189` - route payload contract tests are already used for API shape verification.

  **Acceptance Criteria**:
  - [ ] A new persisted progress record is created/read without requiring manual DB migration.
  - [ ] `GET /api/tasks/{task_id}` includes structured `execution_progress` for an active ASR task and omits or nulls it when inactive.
  - [ ] Existing task detail consumers remain valid when `execution_progress` is absent.

  **QA Scenarios**:
  ```
  Scenario: active ASR task returns structured progress
    Tool: Bash
    Steps: run backend tests that seed an active task with progress state and query task detail serialization
    Expected: serialized payload contains current phase, heartbeat, and timings in a stable shape
    Evidence: .sisyphus/evidence/task-1-progress-contract.txt

  Scenario: legacy task detail without progress remains valid
    Tool: Bash
    Steps: run existing task detail API tests against tasks with no progress row
    Expected: API returns 200 and existing fields remain unchanged
    Evidence: .sisyphus/evidence/task-1-legacy-compat.txt
  ```

  **Commit**: YES | Message: `feat(backend): add asr execution progress contract` | Files: `backend/app/models.py`, `backend/app/repositories/tasks.py`, `backend/app/api/routes/tasks.py`, relevant tests

- [x] 2. Define the ASR child-runner protocol and result manifest

  **What to do**: Extract the current ASR core flow into a child-runner module/entrypoint that performs the same quality-preserving sequence (`model_load`, `vad`, `transcribe`, `align`, `persist`) but emits structured JSONL progress events to stdout and writes a result manifest under the task work directory. The child must not mutate DB state directly. The JSONL protocol is fixed to these events:
  - `phase_start`: `{"event":"phase_start","phase":"vad","phase_index":2,"phase_count":5,"message":"starting vad","ts":"ISO-8601"}`
  - `heartbeat`: `{"event":"heartbeat","phase":"transcribe","phase_index":3,"phase_count":5,"elapsed_ms":12345,"message":"transcribe running","ts":"ISO-8601"}`
  - `phase_complete`: `{"event":"phase_complete","phase":"align","phase_index":4,"phase_count":5,"elapsed_ms":2345,"ts":"ISO-8601"}`
  - `failure`: `{"event":"failure","phase":"align","code":"alignment_failed","message":"...","ts":"ISO-8601"}`
  - `success`: `{"event":"success","phase":"persist","elapsed_ms_total":45678,"manifest_path":"/abs/path/asr-result.json","ts":"ISO-8601"}`
  The child writes `asr-result.json` with exact top-level keys: `status`, `elapsed_ms_total`, `phases`, `artifacts`, `model_metadata`, and `error`.
  **Must NOT do**: Do not change model size, precision, or alignment behavior. Do not duplicate ASR business logic in two divergent code paths; keep one shared core implementation.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: ML stage refactor with IO contract.
  - Skills: [`senior-backend`, `senior-ml-engineer`] - reason: process contract + model pipeline invariants.
  - Omitted: [`senior-frontend`] - reason: no UI work here.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: 4, 7 | Blocked By: none

  **References**:
  - Pattern: `backend/app/services/asr_whisperx.py:205-330` - preserve the existing ASR algorithm and artifact outputs.
  - Pattern: `backend/app/services/asr_whisperx.py:223-250` - current core phases that must become first-class progress events.
  - Pattern: `backend/app/services/asr_whisperx.py:343-347` - preserve existing model metadata fields in the result manifest.
  - Test: `backend/tests/test_asr_whisperx.py:67-112` - current device/compute/alignment path is already asserted; preserve behavior.
  - External: `https://github.com/m-bain/whisperX/blob/main/README.md` - current upstream phase expectations.

  **Acceptance Criteria**:
  - [ ] Child runner emits parseable JSONL phase events in deterministic order.
  - [ ] Child runner writes a manifest containing artifact paths, elapsed timings, and model metadata sufficient for the parent to publish results.
  - [ ] Success/failure outputs are equivalent in semantics to the current in-process ASR stage.

  **QA Scenarios**:
  ```
  Scenario: child runner emits full success protocol
    Tool: Bash
    Steps: invoke focused backend tests with a fake/model-stubbed child runner and capture stdout JSONL
    Expected: events cover model_load, vad, transcribe, align, persist, terminal success in order
    Evidence: .sisyphus/evidence/task-2-child-success.jsonl

  Scenario: child runner emits classified failure protocol
    Tool: Bash
    Steps: force a known ASR failure path in test mode and capture child output + manifest absence/presence rules
    Expected: failure event includes stable error code and no parent-publishable success manifest is produced
    Evidence: .sisyphus/evidence/task-2-child-failure.jsonl
  ```

  **Commit**: YES | Message: `feat(asr): define child runner protocol` | Files: `backend/app/services/asr_whisperx.py`, new ASR child-runner module, relevant tests

- [x] 3. Add a tracked streaming subprocess helper for structured phase events

  **What to do**: Add a new helper in `pipeline_support.py` (or equivalent) that launches a process group, streams line-buffered stdout incrementally, parses JSONL progress events, updates heartbeat, mirrors human-readable lines into the stage log, and supports graceful cancel followed by force-kill after a fixed timeout. The timeout decision is fixed for this phase: send `SIGTERM`, wait **10 seconds**, then escalate to `SIGKILL` if the child process group still exists. The helper must return the terminal child result and expose parsed phase/timing state to the caller.
  **Must NOT do**: Do not retrofit the old `run_tracked_process_group_command()` with ambiguous dual behavior; add a dedicated structured-progress variant. Do not let malformed child output crash the parent without a classified failure.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: process orchestration, signal semantics, and parser robustness.
  - Skills: [`senior-backend`] - reason: subprocess, signal, and session boundary work.
  - Omitted: [`senior-frontend`] - reason: backend-only helper.

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: 4, 5, 7 | Blocked By: none

  **References**:
  - Pattern: `backend/app/services/pipeline_support.py:38-125` - existing tracked subprocess/cancel/kill contract to mirror.
  - Pattern: `backend/app/services/pipeline_support.py:142-180` - current active process-group heartbeat handling.
  - Pattern: `backend/app/services/task_control.py:154-170` - reusable heartbeat semantics.
  - Test: `backend/tests/test_worker_cancellation.py:537-848` - kill and graceful cancel patterns already exercised for tracked subprocesses.

  **Acceptance Criteria**:
  - [ ] Parent streams progress incrementally while child is running.
  - [ ] Heartbeat updates occur without waiting for child exit.
  - [ ] Graceful cancel sends `SIGTERM`, waits a bounded grace period, then escalates to `SIGKILL` when necessary.

  **QA Scenarios**:
  ```
  Scenario: structured helper streams progress and heartbeats
    Tool: Bash
    Steps: run backend tests with a fake long-running child that emits JSONL progress events over time
    Expected: parent updates heartbeat multiple times before child exit and log file contains phase lines in order
    Evidence: .sisyphus/evidence/task-3-streaming-helper.txt

  Scenario: malformed child event fails predictably
    Tool: Bash
    Steps: run a fake child that emits invalid JSONL after startup
    Expected: parent records a classified failure and finalizes the stage instead of hanging
    Evidence: .sisyphus/evidence/task-3-malformed-event.txt
  ```

  **Commit**: YES | Message: `feat(worker): add tracked streaming subprocess helper` | Files: `backend/app/services/pipeline_support.py`, relevant tests

- [x] 4. Wire ASR through parent-owned subprocess orchestration

  **What to do**: Replace the direct `STAGE_EXECUTORS["asr"] = transcribe_task_audio` path with a parent-owned wrapper that launches the ASR child, feeds it the task context, consumes structured events, updates the new progress state, and only after child success publishes artifact metadata and final stage status. Parent remains the sole owner of task/job/stage terminal transitions.
  **Must NOT do**: Do not let the child publish artifacts directly to DB. Do not keep a second code path where in-process ASR can silently bypass progress/cancel semantics.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: central stage integration and execution-token correctness.
  - Skills: [`senior-backend`, `systematic-debugging`] - reason: worker/task-runner integration with failure-mode discipline.
  - Omitted: [`senior-frontend`] - reason: no UI in this task.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 5, 6, 7, 8 | Blocked By: 1, 2, 3

  **References**:
  - Pattern: `backend/app/services/task_runner.py:89-97` - current stage wiring entrypoint.
  - Pattern: `backend/app/services/task_runner.py:100-218` - current parent-owned task/job/stage lifecycle.
  - Pattern: `backend/app/services/storage.py:67-87` - artifact persistence must remain guarded by current execution context.
  - Test: `backend/tests/test_task_runner.py:64-188` - canonical stage-order and failure checkpoint behavior must be preserved.

  **Acceptance Criteria**:
  - [ ] `asr` runs only through the subprocess wrapper in the worker path.
  - [ ] Parent task/job/stage state remains authoritative before, during, and after ASR.
  - [ ] Successful ASR still produces the same logical downstream artifacts and completion semantics.

  **QA Scenarios**:
  ```
  Scenario: ASR stage executes through child and parent publishes results
    Tool: Bash
    Steps: run focused task-runner tests with a successful ASR child stub and inspect task/job/stage/artifact DB state
    Expected: parent transitions asr to success, advances checkpoint to translation, and publishes transcript/subtitle/alignment artifacts
    Evidence: .sisyphus/evidence/task-4-asr-parent-success.txt

  Scenario: child crash does not leave parent half-updated
    Tool: Bash
    Steps: run a failing child stub that exits non-zero after phase_start
    Expected: task/job/stage finalize to failed with no success artifacts published and no stale execution token left behind
    Evidence: .sisyphus/evidence/task-4-asr-parent-failure.txt
  ```

  **Commit**: YES | Message: `feat(asr): run asr via tracked subprocess` | Files: `backend/app/services/task_runner.py`, `backend/app/services/asr_whisperx.py`, helper modules, relevant tests

- [x] 5. Extend ASR cancel, force-kill, and stale recovery semantics

  **What to do**: Extend killable-stage handling so `asr` is killable **only when** a tracked process group exists. On cancel, parent sends `SIGTERM`, waits **10 seconds**, and only then finalizes `cancelled` after child exit or escalates to `SIGKILL`. On force-kill, parent sends `SIGKILL` immediately. Update stale recovery so a stale ASR process-group is best-effort killed before the task is marked failed and the queue is unblocked. Preserve the already-fixed orphaned-running-job behavior when control rows are missing.
  **Must NOT do**: Do not make in-process ASR look killable without a process group. Do not regress current `ingest`/`media_prep` behavior. Do not clear running state before child termination attempt.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: concurrency, stale recovery, and kill semantics.
  - Skills: [`senior-backend`, `systematic-debugging`] - reason: subtle failure and recovery path changes.
  - Omitted: [`senior-frontend`] - reason: backend-only semantics.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 7, 8 | Blocked By: 3, 4

  **References**:
  - Pattern: `backend/app/services/task_control.py:10, 32-33, 102-118, 195-227` - current cancel/force-kill/finalize contract.
  - Pattern: `backend/app/worker.py:127-154` - stale-running-job recovery and queue claim gate.
  - Test: `backend/tests/test_worker_cancellation.py:537-848` - existing tracked subprocess cancel/kill behavior for other stages.
  - Test: `backend/tests/test_worker_cancellation.py:862-962` - orphaned running GPU jobs must still fail and unblock the next claim.
  - Oracle guardrail: stale ASR recovery must attempt pgid kill before failing/unblocking.

  **Acceptance Criteria**:
  - [ ] Cancel during active ASR reaches terminal `cancelled` within the configured grace window once the child responds to `SIGTERM`.
  - [ ] Force-kill during active ASR reaches terminal `cancelled` and clears active process group state.
  - [ ] Stale ASR process-group recovery kills the recorded child group before failing/unblocking the queue.

  **QA Scenarios**:
  ```
  Scenario: graceful cancel during transcribe phase
    Tool: Bash
    Steps: run a fake long-running ASR child, issue /cancel while current_phase=transcribe, wait for worker to finalize
    Expected: child receives SIGTERM, task detail flips to cancel_requested immediately, then final task/job/stage become cancelled
    Evidence: .sisyphus/evidence/task-5-asr-cancel.txt

  Scenario: stale ASR process group is killed before queue unblocks
    Tool: Bash
    Steps: seed a stale running asr job with heartbeat/process_group metadata and a live child, then invoke claim_next_job path
    Expected: stale child process group is terminated, stale task is failed, next pending job is claimable
    Evidence: .sisyphus/evidence/task-5-asr-stale-recovery.txt
  ```

  **Commit**: YES | Message: `fix(worker): add cancellable asr lifecycle` | Files: `backend/app/services/task_control.py`, `backend/app/worker.py`, `backend/app/api/routes/tasks.py`, relevant tests

- [x] 6. Surface ASR phase/timing progress in the frontend task detail UI

  **What to do**: Extend frontend task detail types and rendering to show the active ASR phase, elapsed time, last heartbeat timestamp, and completed phase timings. Preserve the existing distinction between overlaid task-detail status (`cancel_requested`) and raw stage list status. When cancellation is pending, render copy that explicitly says the system is waiting for the current ASR child phase/process to stop.
  **Must NOT do**: Do not rely on the raw `/stages` endpoint alone for cancel visualization. Do not hide existing stage-level logs or control buttons unless the new progress state makes them invalid.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: UI state/rendering changes with user-facing copy.
  - Skills: [`senior-frontend`] - reason: React task detail state and API typing.
  - Omitted: [`senior-backend`] - reason: backend contract should already be ready from Tasks 1/4/5.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: 7 | Blocked By: 1, 4

  **References**:
  - Pattern: `web/src/pages/TaskDetailPage.tsx:148-178` - current polling surface and task-detail preference path.
  - Pattern: `web/src/lib/types.ts:65-75` - current task-detail contract.
  - Pattern: `web/src/components/EnvironmentStatusCard.tsx:54-73` - existing degraded-state rendering style for operational status.
  - Test: `web/src/pages/__tests__/TaskDetailPage.test.tsx` - current task-detail assertions and cancel-related rendering.

  **Acceptance Criteria**:
  - [ ] Active ASR tasks display current phase and elapsed timing in task detail.
  - [ ] Cancelled-in-flight ASR displays an explicit `cancel_requested` waiting message without pretending the task is idle.
  - [ ] Existing task detail rendering for non-ASR stages remains valid.

  **QA Scenarios**:
  ```
  Scenario: running ASR shows structured phase progress
    Tool: Playwright
    Steps: open a stubbed task detail page whose detail payload includes execution_progress.current_phase=align and completed timings for earlier phases
    Expected: UI shows active phase align, completed phase timings, and no unavailable fallback
    Evidence: .sisyphus/evidence/task-6-asr-progress.png

  Scenario: cancel_requested ASR shows waiting copy
    Tool: Playwright
    Steps: open a stubbed task detail page with status cancel_requested, active_stage_name=asr, and progress payload still active
    Expected: UI indicates cancellation is pending for the current ASR execution and disables the regular cancel button
    Evidence: .sisyphus/evidence/task-6-asr-cancel-requested.png
  ```

  **Commit**: YES | Message: `feat(web): show asr execution progress` | Files: `web/src/lib/types.ts`, `web/src/lib/api.ts`, `web/src/pages/TaskDetailPage.tsx`, relevant tests/copy

- [x] 7. Add focused regression coverage for ASR lifecycle and surfacing

  **What to do**: Expand backend and frontend tests so the new ASR lifecycle is protected end-to-end. This includes child protocol parsing, progress serialization, graceful cancel, force-kill, stale recovery with process-group cleanup, and UI rendering of `execution_progress` plus `cancel_requested` overlays.
  **Must NOT do**: Do not rely on a single happy-path smoke test. Do not leave stale recovery or malformed event parsing untested.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: cross-layer regression design.
  - Skills: [`senior-qa`, `tdd-guide`] - reason: precise backend/frontend regression coverage.
  - Omitted: [`senior-frontend`] - reason: UI logic itself belongs to Task 6.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: 8, Final Verification | Blocked By: 1, 2, 3, 4, 5, 6

  **References**:
  - Test: `backend/tests/test_worker_cancellation.py:264-848, 862-962` - current cancellation/stale-recovery patterns to extend.
  - Test: `backend/tests/test_asr_whisperx.py:24-439` - current ASR path behavior and device/config forwarding.
  - Test: `backend/tests/test_task_runner.py:64-188` - stage-order and failure semantics.
  - Test: `web/src/test/smoke.test.tsx` - shell remains usable under degraded operational states.

  **Acceptance Criteria**:
  - [ ] All newly introduced ASR cancel/progress paths are covered by backend tests.
  - [ ] Frontend tests cover active progress rendering and cancel-pending rendering.
  - [ ] Existing unrelated worker/task regressions remain green.

  **QA Scenarios**:
  ```
  Scenario: full focused regression suite passes
    Tool: Bash
    Steps: run backend + frontend targeted test commands for ASR lifecycle and task detail rendering
    Expected: all focused tests pass with no new failures in existing worker/task suites
    Evidence: .sisyphus/evidence/task-7-regressions.txt

  Scenario: malformed child event does not wedge UI-visible task state
    Tool: Bash
    Steps: run backend tests with malformed child event input and inspect task detail/log output contract
    Expected: task finalizes to failed with a deterministic summary and no permanent running/cancel_requested limbo
    Evidence: .sisyphus/evidence/task-7-malformed-event.txt
  ```

  **Commit**: YES | Message: `test(asr): cover subprocess cancel and progress flow` | Files: backend/frontend tests only

- [x] 8. Update operator and developer documentation for the new ASR lifecycle

  **What to do**: Update the operator/deployment/user-facing docs to explain the new ASR phase model, cancel semantics, what `cancel_requested` means during ASR, and how to read the new progress/timing outputs. Include explicit note that this phase does **not** yet change model quality/performance knobs, but now provides the evidence needed for later tuning.
  **Must NOT do**: Do not document speculative CPU/GPU conclusions or future speed optimizations as implemented behavior.

  **Recommended Agent Profile**:
  - Category: `writing` - Reason: operational docs and behavior explanations.
  - Skills: [`roadmap-communicator`] - reason: clear behavior change communication.
  - Omitted: [`senior-backend`] - reason: docs should reflect already-implemented behavior, not invent it.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: Final Verification | Blocked By: 4, 5, 6, 7

  **References**:
  - Pattern: `docs/operator-manual.md:201-230` - current runtime and issue-code explanation style.
  - Pattern: `docs/deployment-guide.md:453-471` - current operator troubleshooting framing.
  - Pattern: `backend/app/repositories/tasks.py:102-117` - cancel_requested overlay semantics that docs must explain accurately.
  - External: `https://github.com/m-bain/whisperX/blob/main/README.md` - upstream phase expectations for terminology only.

  **Acceptance Criteria**:
  - [ ] Operator docs explain active ASR progress, cancel_requested waiting semantics, and final cancelled transition.
  - [ ] Docs state that quality-preserving speed tuning is out of scope for this phase.
  - [ ] Docs align with actual API/UI behavior introduced by Tasks 1, 5, and 6.

  **QA Scenarios**:
  ```
  Scenario: docs match implemented API/UI semantics
    Tool: Bash
    Steps: compare final docs wording against backend/frontend tests and grep for stale contradictory statements
    Expected: no docs claim that cancel during ASR is immediate before the child process exits
    Evidence: .sisyphus/evidence/task-8-doc-consistency.txt

  Scenario: no stale CPU/GPU optimization claims added
    Tool: Bash
    Steps: grep updated docs for unsupported performance promises or quality-changing defaults
    Expected: docs remain scoped to cancellation/progress behavior only
    Evidence: .sisyphus/evidence/task-8-scope-guard.txt
  ```

  **Commit**: YES | Message: `docs(asr): explain cancellable progress lifecycle` | Files: relevant docs under `docs/`

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [x] F1. Plan Compliance Audit — oracle
- [x] F2. Code Quality Review — unspecified-high
- [x] F3. Real Manual QA — unspecified-high (+ playwright if UI)
- [x] F4. Scope Fidelity Check — deep

## Commit Strategy
- Commit 1: backend progress persistence + child protocol + streaming helper
- Commit 2: ASR subprocess orchestration + cancel/stale recovery semantics
- Commit 3: frontend progress UI + regressions + docs
- If implementation needs finer granularity, preserve these logical boundaries and keep each commit independently passing its targeted tests.

## Success Criteria
- A running ASR task surfaces phase/timing progress without relying on raw log tail reading.
- Cancelling during ASR transitions immediately to `cancel_requested` in task detail and reaches terminal `cancelled` once the child exits or is force-killed.
- Force-kill is available for active ASR only while a tracked process group exists.
- Stale ASR subprocesses are killed/recovered without leaving the queue blocked.
- No transcription-quality defaults are reduced in this phase.
