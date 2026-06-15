## 2026-06-16 - TDD Wave 1 status recovery tests

- Existing backend task detail serialization lives in `backend/app/repositories/tasks.py` via `_task_to_response()` and currently only emits `failure_recovery` for ASR `summary == "missing_model"`.
- Existing `/api/tasks/{task_id}/logs` payload has `stage_name`, `status`, `summary`, and `log_path`; new tests now define the desired `display_label` and redacted `safe_summary` contract.
- Retry tests already preserve upstream stage statuses and clear ASR progress when retrying from ASR; added red/guard coverage for preserving ASR progress when retry starts after ASR.
- No Alembic is present; schema migration test defines desired `init_db()` behavior for adding `taskstage.failure_code` to pre-change SQLite schemas while preserving existing rows.
- Red check confirmed: `uv run --project backend pytest backend/tests/test_tasks_api.py::test_task_detail_exposes_failure_code_and_recovery_actions -q` fails on missing `failure_code` in task detail JSON.

## 2026-06-16 - T1 backend status recovery green phase

- Added `TaskStage.failure_code` as a nullable, lightweight-migrated SQLite column; `init_db()` now patches existing `taskstage` tables without Alembic.
- Failure-code taxonomy lives in `backend/app/services/failure_codes.py`; ASR legacy summaries like `missing_model`, `oom`, and `alignment_failed` are normalized to UI-facing `asr_*` failure codes without changing existing summaries.
- Recovery actions are serialized in `backend/app/services/recovery_actions.py`; failed tasks expose retry actions, and ASR missing-model failures prepend the model download action.
- Task detail now includes `failure_code`, `recovery_actions`, and `artifact_readiness`; readiness currently uses public artifact kinds and aliases internal persisted kinds such as `asr_audio` and `bilingual_transcript_json`.
- Log summaries now include `display_label` and `safe_summary`, with token/path/env-style redaction while preserving the existing `summary` and pseudo `/data/tasks/...` log path contract.
- Verification: `uv run --project backend pytest backend/tests/test_tasks_api.py backend/tests/test_retry_api.py backend/tests/test_retry_resume.py backend/tests/test_schema_migration.py -q` passed: 22 passed, 1 warning.

## 2026-06-16 - T3 frontend status recovery contracts

- Frontend contract mirrors now model task/stage `failure_code`, recovery actions, artifact readiness, safe log summaries, and optional execution control state in `web/src/lib/types.ts`.
- Backend tests in this branch currently serialize recovery actions with `label`/`href`/`payload`; frontend types also accept `label_key`/`description_key`/`endpoint`/`confirmation_required`/`success_behavior` for the planned copy-key contract.
- `web/src/lib/taskState.ts` centralizes state-matrix classification without parsing human summaries; retryability is based on enabled `retry_stage` recovery actions and their stage payload when present.
- Vitest path filtering runs from the `web/` package cwd; `pnpm --dir web test --run ../web/src/lib/__tests__/api.test.ts ../web/src/lib/__tests__/taskState.test.ts` is the bounded equivalent of the plan's root-relative targeted test command.
- Verification: targeted lib tests passed (28 tests) and `pnpm --dir web build` passed.

## 2026-06-16 - Wave 3 workspace artifact states and export validation

- `WorkspacePage` can consume optional `artifactReadiness` records directly, so T4 can wire task-detail readiness without changing workspace rendering internals.
- Workspace artifact sections now classify query failures via `classifyArtifactReadiness("load_error")`; load errors render retry buttons and are not collapsed into empty data.
- Export range validation is client-side and preserves edited input strings on both validation failures and backend export errors.
- Verification: `pnpm --dir web test --run src/pages/__tests__/WorkspacePage.test.tsx` passed (6 tests).

## 2026-06-16 - Wave 3 TaskDetail status recovery UI

- `TaskDetailPage` now routes task-detail presentation through `classifyTaskState`, `getPrimaryAction`, and `isRetryable`; generic retry actions use the backend `retry_stage` contract instead of summary parsing.
- Stage logs should prefer `display_label` and `safe_summary` in the timeline; raw `log_path` remains available only under the `技术日志路径` disclosure for operator diagnostics.
- ASR missing-model recovery keeps the existing model-download endpoint but changes the primary action copy to `下载缺失模型` to match the recovery-action contract.
- Verification: `pnpm --dir web test --run -- src/pages/__tests__/TaskDetailPage.test.tsx` passed (52 tests across the web Vitest suite because the command form runs all configured tests).

## 2026-06-16 - Wave 4 deterministic Playwright recovery journeys

- `TaskDetailPage` now passes backend `artifact_readiness` into `WorkspacePage`, so E2E fixtures can assert readiness-contract driven workspace states rather than relying on missing artifact fallbacks.
- Task detail Playwright fixtures must include safe summaries for pending log records; otherwise `classifyTaskState` correctly treats pending empty logs as `log_not_ready` before generic failed-state rendering.
- Added routed E2E coverage for ASR missing-model download action with raw log paths hidden behind `技术日志路径`, generic translation retry payloads, task-not-found recovery, artifact not-ready/load-error states, and client-side export range blocking with no `/clips` request.
- Requirements exports were stale before final verification; regenerated them with `./scripts/export_backend_requirements.sh` and verified `./scripts/export_backend_requirements.sh --check` afterwards.
- Verification: `pnpm --dir web test --run && pnpm --dir web build && pnpm --dir web test:e2e -- task-detail.spec.ts workspace.spec.ts && ./scripts/export_backend_requirements.sh --check` passed (52 Vitest tests, production build, 9 Playwright tests, all requirements files up to date).
