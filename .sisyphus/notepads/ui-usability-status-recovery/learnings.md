## 2026-06-16 - TDD Wave 1 status recovery tests

- Existing backend task detail serialization lives in `backend/app/repositories/tasks.py` via `_task_to_response()` and currently only emits `failure_recovery` for ASR `summary == "missing_model"`.
- Existing `/api/tasks/{task_id}/logs` payload has `stage_name`, `status`, `summary`, and `log_path`; new tests now define the desired `display_label` and redacted `safe_summary` contract.
- Retry tests already preserve upstream stage statuses and clear ASR progress when retrying from ASR; added red/guard coverage for preserving ASR progress when retry starts after ASR.
- No Alembic is present; schema migration test defines desired `init_db()` behavior for adding `taskstage.failure_code` to pre-change SQLite schemas while preserving existing rows.
- Red check confirmed: `uv run --project backend pytest backend/tests/test_tasks_api.py::test_task_detail_exposes_failure_code_and_recovery_actions -q` fails on missing `failure_code` in task detail JSON.
