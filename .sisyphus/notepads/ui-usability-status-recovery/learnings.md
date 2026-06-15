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
