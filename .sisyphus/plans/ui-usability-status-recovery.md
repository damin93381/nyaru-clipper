# UI Usability Status Recovery Optimization

## TL;DR
> **Summary**: Make Nyaru-Clipper's UI trustworthy during long-running processing by adding structured backend recovery/status contracts, frontend state helpers, clearer failure actions, artifact/log readiness states, and deterministic tests.
> **Deliverables**:
> - Backend contract for machine-readable stage failure codes, recovery actions, artifact readiness, and log readiness.
> - Frontend status/error/recovery rendering for task detail and workspace.
> - Client-side export range validation.
> - TDD coverage across pytest, Vitest, and mocked Playwright journeys.
> **Effort**: Large
> **Parallel**: YES - 4 waves
> **Critical Path**: Contract tests → backend contract implementation → frontend types/helpers → UI flows → E2E smoke

## Context
### Original Request
The user is dissatisfied with the current UI and feature usability and asked for analysis plus a comprehensive optimization plan. They selected: functional usability over pure visual redesign, status/error recovery as first priority, contract-first status recovery, larger backend/API changes allowed, and TDD.

### Interview Summary
- Visual companion declined; use text-only planning.
- First-round scope is **status and error recovery**, not full task history or visual redesign.
- Backend/API changes may be substantial if they make UI state reliable.
- Preserve MVP constraints: LAN/single-host, single GPU-bound worker, no auth/TLS/multi-user, no Redis/Celery/Prefect, Docker fallback only.

### Research Findings
- Routes: `web/src/router.tsx` only exposes `/` and `/tasks/:taskId`; `TaskDetailPage` embeds `WorkspacePage`.
- UI gaps: placeholder panels/controls, informational toggles, misleading workspace empty states, no export client validation, raw log paths, weak failure next-actions.
- Test baseline exists: `web/package.json`, `web/vite.config.ts`, `web/playwright.config.ts`, page/API Vitest tests, Playwright specs, `scripts/_release_smoke_common.sh`.
- Backend APIs already exist for create/detail/stages/artifacts/logs/artifact content/retry/cancel/force-kill/ASR model download/clips.
- Retry semantics are already reliable and must be preserved: retry selected stage + downstream, keep upstream success, clear ASR progress when retrying from/before ASR.
- Only ASR missing-model has structured `failure_recovery`; other failures use status + summary + logs.
- No Alembic/migration framework exists; DB init uses `SQLModel.metadata.create_all(get_engine())` in `backend/app/db.py`.

### Metis Review (gaps addressed)
- Added explicit state matrix requirement.
- Kept task history/list route out of scope.
- Chose persisted `TaskStage.failure_code` plus lightweight startup schema migration instead of UI string-matching.
- Added redaction rules for log/path display.
- Required deterministic tests with mocked/seeded states; no Bilibili, WhisperX, ROCm, GPU, or model weights in automated UI tests.

## Work Objectives
### Core Objective
Users should always understand whether a task/workspace artifact/log is loading, waiting, missing, failed, recoverable, cancelled, or ready, and should see the next safe action without reading raw filesystem paths or backend implementation details.

### Deliverables
- Add backend stage failure contract fields and recovery action serialization.
- Add backend readiness contracts for expected artifacts and per-stage logs.
- Add safe log/path presentation fields.
- Update frontend types and API tests.
- Add frontend state matrix helpers and centralized Chinese copy.
- Update `TaskDetailPage` status/failure/recovery UI.
- Update `WorkspacePage` artifact query states and export validation.
- Add deterministic pytest, Vitest, and Playwright coverage.

### Definition of Done (verifiable conditions with commands)
- `uv run --project backend pytest backend/tests/test_tasks_api.py backend/tests/test_retry_api.py backend/tests/test_retry_resume.py backend/tests/test_task_execution_progress_repo.py`
- `pnpm --dir web test -- --run`
- `pnpm --dir web test:e2e -- task-detail.spec.ts workspace.spec.ts`
- `pnpm --dir web build`
- `./scripts/export_backend_requirements.sh --check`

### Must Have
- Preserve existing retry/resume behavior.
- Backend and frontend stage/status contracts stay synchronized.
- Recovery actions are machine-readable and copy-key based.
- Log display never exposes raw filesystem paths by default.
- UI differentiates loading, not ready, missing, failed, load error, and ready states for workspace artifacts/logs.
- Automated tests use deterministic API fixtures/mocks only.

### Must NOT Have
- No task history/list route in this plan.
- No full visual redesign or design-system replacement.
- No auth/TLS/multi-user/public internet hardening.
- No Redis/Celery/Prefect or multi-worker assumptions.
- No tests requiring real Bilibili downloads, WhisperX, model weights, GPU, ROCm, or LAN network access.
- No frontend parsing of human summary strings for core recovery decisions.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: TDD across pytest, Vitest, and Playwright.
- QA policy: Every task has agent-executed happy and failure scenarios.
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.{ext}`

## State Matrix
| State | Backend Contract | UI Location | Primary Action |
| --- | --- | --- | --- |
| new task / no task | no task id | `NewTaskPage` | create task |
| queued | task/job pending | `TaskDetailPage` | wait, refresh |
| active stage | task/stage running + optional `execution_progress` | `TaskDetailPage` | cancel if allowed |
| stage failed generic | `stage.status=failed`, `failure_code != null`, `recovery_actions` includes `retry_stage` when safe | `TaskDetailPage` | retry stage |
| ASR missing model | `failure_code=asr_missing_model`, `failure_recovery.kind=missing_model`, action `download_asr_model` | `TaskDetailPage` | download model, retry ASR |
| artifact not ready | artifact readiness `not_ready` | `WorkspacePage` | wait / inspect stage |
| artifact missing | artifact readiness `missing` after producing stage terminal | `WorkspacePage` | retry producing stage |
| artifact failed | artifact readiness `failed` from producing stage failure | `WorkspacePage` | view recovery action |
| artifact load error | frontend query/network/API error | `WorkspacePage` | retry loading section |
| log not ready | log readiness `not_ready` before stage starts | `TaskDetailPage` | wait |
| log load error | frontend query/network/API error | `TaskDetailPage` | retry logs |
| cancelled | task/status cancelled | `TaskDetailPage` | start new task |
| force-kill requested | control force-kill requested | `TaskDetailPage` | wait for worker |
| retry in progress | task pending/running after retry response | `TaskDetailPage` | wait |
| worker stale recovery | `failure_code=stale_job_recovered` | `TaskDetailPage` | retry failed stage |
| task not found | HTTP 404 | `TaskDetailPage` | back to new task |

## Contract Decisions
- Add nullable `failure_code: str | None` to `TaskStage` and expose it in task detail/stages. Do not remove `summary`; keep it human-readable/backward-compatible.
- Add a lightweight startup schema migration for existing SQLite DBs because no Alembic exists.
- Recovery metadata is response-derived from task/stage/control state plus `failure_code`, except ASR missing-model model readiness continues using existing ASR recovery helpers.
- `recovery_actions` are serialized in API responses, not persisted.
- Artifact/log readiness is response-derived from expected artifact kinds, stage status, artifact rows, and frontend query state.
- Raw `log_path` remains available for operator diagnostics but UI defaults to `display_label` and `safe_summary`.

## Execution Strategy
### Parallel Execution Waves
Wave 1: Backend contract tests and migration tests.
Wave 2: Backend implementation + frontend types/tests in parallel after Wave 1.
Wave 3: TaskDetail and Workspace UI implementation in parallel after Wave 2.
Wave 4: E2E/regression verification and docs/copy cleanup.

### Dependency Matrix
| Task | Blocks | Blocked By |
| --- | --- | --- |
| 1 Backend contract tests | 2 | none |
| 2 Backend contract implementation | 3,4,5 | 1 |
| 3 Frontend contract/types/tests | 4,5 | 2 |
| 4 TaskDetail state/recovery UI | 6 | 3 |
| 5 Workspace artifact/export states | 6 | 3 |
| 6 Playwright journey tests | F1-F4 | 4,5 |

### Agent Dispatch Summary
| Wave | Task Count | Categories |
| --- | ---: | --- |
| 1 | 1 | deep |
| 2 | 2 | deep, visual-engineering |
| 3 | 2 | visual-engineering |
| 4 | 1 | unspecified-high |

## TODOs
> Implementation + Test = ONE task. Never separate.
> EVERY task MUST have: Agent Profile + Parallelization + QA Scenarios.

- [x] 1. Backend Contract Tests for Failure Codes, Recovery Actions, and Readiness

  **What to do**: Add failing pytest coverage before implementation. Tests must assert exact JSON shape for `failure_code`, `recovery_actions`, artifact readiness, log readiness, schema migration behavior, and existing retry semantics. Add/extend tests in `backend/tests/test_tasks_api.py`, `backend/tests/test_retry_api.py`, `backend/tests/test_retry_resume.py`, and a new migration-focused test if needed.
  **Must NOT do**: Do not implement production code in this task before tests fail. Do not require real pipeline/WhisperX/model execution.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: backend contract and persistence behavior must be reasoned through carefully.
  - Skills: `senior-backend`, `api-test-suite-builder`, `tdd-guide` - backend API contracts and TDD.
  - Omitted: `senior-frontend` - no frontend code yet.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: [2] | Blocked By: []

  **References**:
  - Pattern: `backend/app/api/routes/tasks.py:29-222` - existing task endpoints and HTTP guards.
  - Pattern: `backend/app/repositories/tasks.py:29-330` - current serialization and retry reset behavior.
  - API/Type: `backend/app/models.py:60-70` - `TaskStage` fields to extend.
  - Test: `backend/tests/test_tasks_api.py` - task API contract tests.
  - Test: `backend/tests/test_retry_api.py` - retry reset and progress clearing.
  - Test: `backend/tests/test_retry_resume.py` - resume from failed stage + downstream only.

  **Acceptance Criteria**:
  - [ ] `uv run --project backend pytest backend/tests/test_tasks_api.py::test_task_detail_exposes_failure_code_and_recovery_actions -q` fails before implementation and passes after Task 2.
  - [ ] Test asserts a generic failed translation stage response contains `failure_code: "unknown_failure"` and `recovery_actions[0].id: "retry_stage"`.
  - [ ] Test asserts ASR missing-model response contains `failure_code: "asr_missing_model"`, existing `failure_recovery.kind: "missing_model"`, and recovery actions `download_asr_model` then `retry_stage`.
  - [ ] Test asserts cancelled tasks do not expose executable retry actions.
  - [ ] Test asserts artifact readiness values include exactly `ready`, `not_ready`, `missing`, and `failed` for seeded stage/artifact states.
  - [ ] Test asserts log records expose `display_label` and `safe_summary` while retaining `log_path` for diagnostics.
  - [ ] Existing retry tests still prove upstream stages remain successful and ASR progress clears only when retrying from/before ASR.

  **QA Scenarios**:
  ```
  Scenario: Backend contract tests fail before implementation
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_tasks_api.py::test_task_detail_exposes_failure_code_and_recovery_actions -q` immediately after writing tests.
    Expected: FAIL because `failure_code` or `recovery_actions` is absent.
    Evidence: .sisyphus/evidence/task-1-backend-contract-red.txt

  Scenario: Retry regression test remains locked
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_retry_api.py backend/tests/test_retry_resume.py -q`.
    Expected: Existing retry behavior either passes unchanged or fails only where new assertions identify missing contract fields, never because retry semantics changed.
    Evidence: .sisyphus/evidence/task-1-retry-baseline.txt
  ```

  **Commit**: YES | Message: `test(api): lock status recovery contracts` | Files: [`backend/tests/test_tasks_api.py`, `backend/tests/test_retry_api.py`, `backend/tests/test_retry_resume.py`]

- [x] 2. Backend Contract Implementation and Lightweight Schema Migration

  **What to do**: Implement the tests from Task 1. Add `TaskStage.failure_code: str | None`. Add a startup-safe SQLite migration helper because `create_all` will not add columns to existing DBs. Centralize failure-code mapping, recovery action serialization, artifact readiness, log readiness, and log/path sanitization.
  **Must NOT do**: Do not change canonical stage names. Do not remove `summary`. Do not alter retry semantics. Do not expose raw paths as primary UI labels.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: cross-cutting backend contract/persistence change.
  - Skills: `senior-backend`, `sql-database-assistant`, `api-design-reviewer` - SQLModel/SQLite migration and API shape.
  - Omitted: `database-schema-designer` - only one nullable column and lightweight migration, not schema redesign.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: [3,4,5] | Blocked By: [1]

  **References**:
  - Pattern: `backend/app/db.py:34` - current `SQLModel.metadata.create_all(get_engine())` initialization.
  - API/Type: `backend/app/models.py:60-70` - extend `TaskStage`.
  - Pattern: `backend/app/services/task_runner.py:226-574` - where failures are marked and retry/resume happens.
  - Pattern: `backend/app/services/asr_whisperx.py:265-310`, `backend/app/services/asr_whisperx.py:970-1005` - ASR missing-model recovery and failure classification.
  - Pattern: `backend/app/services/storage.py:13-83` - log/artifact path helpers.
  - Pattern: `backend/app/repositories/tasks.py:29-330` - serialization layer.

  **Acceptance Criteria**:
  - [ ] `TaskStage.failure_code` exists as nullable column and old SQLite DBs get it via startup migration without data loss.
  - [ ] Failure code taxonomy includes at minimum: `unknown_failure`, `asr_missing_model`, `asr_oom`, `asr_alignment_failed`, `asr_child_failed`, `malformed_progress_event`, `stale_job_recovered`, `cancelled`.
  - [ ] Recovery action object includes exact fields: `id`, `label_key`, `description_key`, `enabled`, `disabled_reason`, `method`, `endpoint`, `confirmation_required`, `success_behavior`.
  - [ ] Generic failed stages expose enabled `retry_stage` only when task is terminal failed and selected stage can be retried.
  - [ ] ASR missing-model exposes `download_asr_model` and `retry_stage`; retry remains disabled until model readiness is satisfied if backend can determine missing state.
  - [ ] Artifact readiness is computed without requiring content fetches.
  - [ ] Log records include `display_label` and `safe_summary`; `safe_summary` redacts absolute project paths, cookie paths, env var assignments, and home-directory prefixes.
  - [ ] Task 1 pytest commands pass.

  **QA Scenarios**:
  ```
  Scenario: Existing DB migrates safely
    Tool: Bash
    Steps: Run the new migration pytest that creates a pre-change SQLite schema, initializes the app DB layer, and inspects `taskstage` columns.
    Expected: `failure_code` column exists and existing rows remain readable.
    Evidence: .sisyphus/evidence/task-2-schema-migration.txt

  Scenario: Recovery action shape is stable
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_tasks_api.py::test_task_detail_exposes_failure_code_and_recovery_actions -q`.
    Expected: PASS with exact expected JSON fields and no extra user-facing raw path label.
    Evidence: .sisyphus/evidence/task-2-recovery-contract.txt
  ```

  **Commit**: YES | Message: `feat(api): add structured recovery contracts` | Files: [`backend/app/models.py`, `backend/app/db.py`, `backend/app/repositories/tasks.py`, `backend/app/services/task_runner.py`, `backend/app/services/asr_whisperx.py`, `backend/app/services/storage.py`, `backend/tests/*`]

- [x] 3. Frontend Contract Types, API Tests, and State Helpers

  **What to do**: Update frontend contract mirrors in `web/src/lib/types.ts` and API tests. Add a focused helper module for task/stage/workspace state classification, using backend fields instead of summary string parsing. Add centralized copy keys for recovery actions and readiness states.
  **Must NOT do**: Do not implement page rendering in this task. Do not add an i18n framework. Do not parse raw failure summaries for state decisions.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: frontend state/copy foundation for UI changes.
  - Skills: `senior-frontend`, `tdd-guide` - React/Vite types and unit tests.
  - Omitted: `landing-page-generator` - this is app UX, not marketing page generation.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: [4,5] | Blocked By: [2]

  **References**:
  - API/Type: `web/src/lib/types.ts:69-112` - existing task/recovery frontend types.
  - Pattern: `web/src/lib/api.ts:15-64`, `web/src/lib/api.ts:118-132` - API client and artifact URL behavior.
  - Test: `web/src/lib/__tests__/api.test.ts` - existing API contract tests.
  - Copy: `web/src/lib/copy/*.ts` - centralized Chinese UI copy.
  - Style: `web/src/styles.css:1-589` - existing tokens/classes.

  **Acceptance Criteria**:
  - [ ] `TaskStageRecord` includes `failure_code` and stage-level `recovery_actions` if exposed by backend.
  - [ ] Task detail type includes top-level `recovery_actions`, artifact readiness records, and enhanced log records.
  - [ ] New helper tests cover every row in the State Matrix.
  - [ ] Copy keys exist for `retry_stage`, `download_asr_model`, `view_logs`, readiness labels, disabled reasons, and safe fallback failure messages.
  - [ ] `pnpm --dir web test -- --run web/src/lib/__tests__/api.test.ts` passes.

  **QA Scenarios**:
  ```
  Scenario: Frontend state helper classifies generic failed stage
    Tool: Bash
    Steps: Run `pnpm --dir web test -- --run web/src/lib/__tests__/taskState.test.ts`.
    Expected: PASS; fixture with `failure_code: "unknown_failure"` returns state `failed_retryable` and action `retry_stage`.
    Evidence: .sisyphus/evidence/task-3-state-helper.txt

  Scenario: Frontend API types accept ASR recovery payload
    Tool: Bash
    Steps: Run `pnpm --dir web test -- --run web/src/lib/__tests__/api.test.ts`.
    Expected: PASS; mocked task detail response includes `failure_code`, `failure_recovery`, and `recovery_actions` without type errors.
    Evidence: .sisyphus/evidence/task-3-api-types.txt
  ```

  **Commit**: YES | Message: `feat(web): add status recovery contracts` | Files: [`web/src/lib/types.ts`, `web/src/lib/api.ts`, `web/src/lib/copy/*.ts`, `web/src/lib/__tests__/*`]

- [x] 4. Task Detail Status, Failure, Recovery, and Safe Log UI

  **What to do**: Redesign `TaskDetailPage` status presentation around the helper from Task 3. Show distinct panels for queued/running/failed/recoverable/cancelled/not found. Add retry/download actions from backend `recovery_actions`. Replace raw log path as the primary display with `display_label` and `safe_summary`; keep technical details in a disclosure section.
  **Must NOT do**: Do not add task history route. Do not invent frontend-only recovery actions that backend does not expose. Do not hide critical failure information behind nested accordions.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: user-visible React UI with status hierarchy and accessibility.
  - Skills: `senior-frontend`, `a11y-audit` - accessible status/actions.
  - Omitted: `epic-design` - no cinematic redesign; clarity over animation.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: [6] | Blocked By: [3]

  **References**:
  - Pattern: `web/src/pages/TaskDetailPage.tsx:336-522` - current loading/error/recovery gating.
  - Test: `web/src/pages/__tests__/TaskDetailPage.test.tsx` - existing recovery/progress tests.
  - Copy: `web/src/lib/copy/taskDetail.ts` - status/failure copy.
  - Style: `web/src/styles.css:1-589` - reuse panels, pills, summary strips, responsive classes.
  - API: `backend/app/api/routes/tasks.py:29-222` - retry/cancel/model download endpoints.

  **Acceptance Criteria**:
  - [ ] Failed generic stage shows exact title `处理失败` and action button with accessible name `重试此阶段` when backend exposes enabled `retry_stage`.
  - [ ] ASR missing-model shows exact action `下载缺失模型` and preserves existing download behavior.
  - [ ] Cancelled task shows no retry action and displays `任务已取消`.
  - [ ] Logs section displays stage label and safe summary by default; raw path only appears inside a details element labelled `技术日志路径`.
  - [ ] Not-found state provides link/button `返回新建任务`.
  - [ ] Unit tests cover generic failure, ASR recovery, cancelled, stale-progress ignored, and safe log disclosure.

  **QA Scenarios**:
  ```
  Scenario: Generic failed stage exposes retry action
    Tool: Bash
    Steps: Run `pnpm --dir web test -- --run web/src/pages/__tests__/TaskDetailPage.test.tsx -t "renders retry action for generic failed stage"`.
    Expected: PASS; screen contains `处理失败`, button `重试此阶段`, and no raw absolute path outside details.
    Evidence: .sisyphus/evidence/task-4-generic-failure.txt

  Scenario: Cancelled task suppresses retry
    Tool: Bash
    Steps: Run `pnpm --dir web test -- --run web/src/pages/__tests__/TaskDetailPage.test.tsx -t "does not show retry actions for cancelled tasks"`.
    Expected: PASS; screen contains `任务已取消` and query by role button name `重试此阶段` returns null.
    Evidence: .sisyphus/evidence/task-4-cancelled.txt
  ```

  **Commit**: YES | Message: `feat(web): clarify task failure recovery` | Files: [`web/src/pages/TaskDetailPage.tsx`, `web/src/pages/__tests__/TaskDetailPage.test.tsx`, `web/src/lib/copy/taskDetail.ts`, `web/src/styles.css`]

- [x] 5. Workspace Artifact States and Export Validation

  **What to do**: Update `WorkspacePage` to distinguish artifact query loading, backend not-ready/missing/failed readiness, load errors, and true empty data. Add client-side validation for export start/end seconds before calling `/clips`. Surface backend export errors as field/form errors without clearing user input.
  **Must NOT do**: Do not require generated artifacts from a real pipeline in tests. Do not treat query error as empty state. Do not clear edited clip times after failed export.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: workspace UX and form validation.
  - Skills: `senior-frontend`, `form-cro`, `tdd-guide` - form/error usability and tests.
  - Omitted: `page-cro` - this is in-product workflow, not marketing conversion.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: [6] | Blocked By: [3]

  **References**:
  - Pattern: `web/src/pages/WorkspacePage.tsx:170-272` - current artifact queries and export mutation.
  - Pattern: `web/src/pages/WorkspacePage.tsx:299-321`, `web/src/pages/WorkspacePage.tsx:446-488` - current empty states.
  - Pattern: `web/src/pages/WorkspacePage.tsx:377-462` - current candidate range inputs/export.
  - Test: `web/src/pages/__tests__/WorkspacePage.test.tsx` - existing subtitle/export tests.
  - Backend: `backend/tests/test_clip_export_api.py:88-143` - export response shape.

  **Acceptance Criteria**:
  - [ ] Subtitle/artifact sections show `正在加载工作台数据` while query is pending.
  - [ ] Backend readiness `not_ready` shows `该数据尚未生成` rather than `暂无数据`.
  - [ ] Backend readiness `missing` shows `产物缺失，可重试生成阶段` and a retry action only if backend exposes one.
  - [ ] Query load error shows `加载工作台数据失败` with button `重新加载此区域`.
  - [ ] Export validation blocks when `start_s >= end_s` and displays exact error `开始时间必须早于结束时间`.
  - [ ] Export validation blocks negative times and displays `时间不能小于 0 秒`.
  - [ ] Failed export mutation preserves edited inputs.

  **QA Scenarios**:
  ```
  Scenario: Artifact load error is not empty state
    Tool: Bash
    Steps: Run `pnpm --dir web test -- --run web/src/pages/__tests__/WorkspacePage.test.tsx -t "shows artifact load errors separately from empty states"`.
    Expected: PASS; screen contains `加载工作台数据失败` and not `暂无字幕数据` for the same failing query.
    Evidence: .sisyphus/evidence/task-5-artifact-load-error.txt

  Scenario: Invalid export range is blocked client-side
    Tool: Bash
    Steps: Run `pnpm --dir web test -- --run web/src/pages/__tests__/WorkspacePage.test.tsx -t "validates export range before submitting"`.
    Expected: PASS; `exportTaskClip` mock is not called and `开始时间必须早于结束时间` is visible.
    Evidence: .sisyphus/evidence/task-5-export-validation.txt
  ```

  **Commit**: YES | Message: `feat(web): clarify workspace readiness states` | Files: [`web/src/pages/WorkspacePage.tsx`, `web/src/pages/__tests__/WorkspacePage.test.tsx`, `web/src/lib/copy/workspace.ts`, `web/src/styles.css`]

- [x] 6. Deterministic Playwright Journeys and Release Verification

  **What to do**: Add/extend Playwright specs using mocked API route fixtures for failed ASR missing model, generic failed retryable stage, artifact not ready, artifact missing, artifact load error, invalid export range, and task not found. Add stable `data-testid` only where role/text selectors are insufficient.
  **Must NOT do**: Do not depend on dev backend state, real downloads, GPU, or network outside Playwright route fixtures. Do not add brittle selectors based on CSS class names.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: cross-layer E2E verification and release smoke.
  - Skills: `playwright-pro`, `senior-qa`, `verification-before-completion` - robust E2E and evidence.
  - Omitted: `browserstack` - no cross-browser matrix requested.

  **Parallelization**: Can Parallel: NO | Wave 4 | Blocks: [F1-F4] | Blocked By: [4,5]

  **References**:
  - Test: `web/e2e/task-detail.spec.ts` - existing failed task detail coverage.
  - Test: `web/e2e/workspace.spec.ts` - existing workspace/export coverage.
  - Test: `web/e2e/task-flow.spec.ts` - broader route fixture pattern.
  - Config: `web/playwright.config.ts` - dev server/baseURL setup.
  - Script: `scripts/_release_smoke_common.sh` - release verification pattern.

  **Acceptance Criteria**:
  - [ ] Playwright test for ASR missing model verifies button `下载缺失模型` and no raw absolute log path visible before expanding `技术日志路径`.
  - [ ] Playwright test for generic failed translation verifies button `重试此阶段` and mocked retry POST receives `stage_name: "translation"`.
  - [ ] Playwright test for artifact not ready verifies text `该数据尚未生成`.
  - [ ] Playwright test for artifact load error verifies button `重新加载此区域`.
  - [ ] Playwright test for invalid export range verifies no `/clips` request is sent.
  - [ ] `pnpm --dir web test:e2e -- task-detail.spec.ts workspace.spec.ts` passes.
  - [ ] `pnpm --dir web build` passes.
  - [ ] `./scripts/export_backend_requirements.sh --check` passes.

  **QA Scenarios**:
  ```
  Scenario: Playwright generic failure retry journey
    Tool: Bash
    Steps: Run `pnpm --dir web test:e2e -- task-detail.spec.ts -g "generic failed stage can be retried"`.
    Expected: PASS; route fixture observes POST `/api/tasks/task-failed/retry` with `{ "stage_name": "translation" }` and UI returns to pending/running state.
    Evidence: .sisyphus/evidence/task-6-playwright-retry.txt

  Scenario: Release-level frontend verification
    Tool: Bash
    Steps: Run `pnpm --dir web test -- --run && pnpm --dir web build && pnpm --dir web test:e2e -- task-detail.spec.ts workspace.spec.ts`.
    Expected: All commands exit 0.
    Evidence: .sisyphus/evidence/task-6-frontend-release.txt
  ```

  **Commit**: YES | Message: `test(e2e): cover status recovery journeys` | Files: [`web/e2e/task-detail.spec.ts`, `web/e2e/workspace.spec.ts`, `web/src/pages/*.tsx` if test IDs are needed]

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [x] F1. Plan Compliance Audit — oracle
- [x] F2. Code Quality Review — unspecified-high
- [x] F3. Real Manual QA — unspecified-high (+ playwright)
- [x] F4. Scope Fidelity Check — deep

## Commit Strategy
- One commit per task using the specified commit messages.
- Stage only files listed in each task.
- Preserve unrelated existing backend modifications unless the task explicitly touches the same file; inspect diffs before committing.
- Do not amend or force-push.

## Success Criteria
- Users can identify task state and next action without reading raw logs.
- Generic failed stages expose safe retry when backend says retry is allowed.
- ASR missing-model recovery remains supported and clearer.
- Workspace no longer confuses loading/error/not-ready/missing states with empty data.
- Export range errors are caught before backend submission.
- Backend/frontend contracts are locked by tests and release verification commands.
