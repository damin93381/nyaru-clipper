## 2026-05-03T03:45:57Z Task: session-start
Approved architecture: subprocess-isolated ASR child runner, parent-owned DB state, structured JSONL phase events, first-class execution_progress API/UI surface.

## 2026-05-03T03:55:09Z Task: structured-streaming-helper
- Chose a new `run_tracked_structured_process_group_command()` API that returns both the terminal `CompletedProcess` and parsed event state (`events` plus `latest_event`), so later ASR stage code can consume machine-readable progress without changing existing non-structured subprocess callers.
- Cancel handling in the structured helper now mirrors the current execution-control semantics but adds built-in escalation: first `SIGTERM` on cancel request, then `SIGKILL` after a 10-second grace window (overridable in tests), while malformed JSONL output is treated as a classified protocol failure and the child process group is torn down immediately.

## 2026-05-03T05:14:00Z Task: persisted-execution-progress-contract
- Added a dedicated `TaskExecutionProgress` SQLModel table keyed by `task_id` instead of mutating existing task/stage/control tables, matching the repo's no-migration pattern for Wave 1 schema work.
- Kept the task-detail API contract conservative: surface `execution_progress` only when the active stage is `asr` and a persisted progress row exists; otherwise omit the field to preserve legacy payload validity.
- Implemented repository-scoped `upsert_task_execution_progress()` and `clear_task_execution_progress()` helpers in `backend/app/repositories/tasks.py` so persistence can be exercised now and reused by later ASR orchestration work.
- Clearing persisted progress during retries from `asr` or earlier was chosen as the minimal stale-data guardrail within this task's scope, avoiding cross-wave changes to cancellation/finalization orchestration.

## 2026-05-03T04:14:41Z Task: child-runner-protocol
- Kept the fixed child event families limited to `phase_start`, `heartbeat`, `phase_complete`, `failure`, and `success`, with the plan's five ASR phases in deterministic order.
- Used `asr-result.json` as a task-local handoff manifest with exact top-level keys `status`, `elapsed_ms_total`, `phases`, `artifacts`, `model_metadata`, and `error`, while keeping DB mutation in the parent path only.

## 2026-05-03T06:26:00Z Task: child-runner-protocol-implementation
- Finalized the shared WhisperX core as `execute_asr_pipeline(...)` inside `backend/app/services/asr_whisperx.py`, with `transcribe_task_audio(...)` remaining the parent DB-writing wrapper and `backend/app/services/asr_child_runner.py` becoming the protocol/manifest wrapper.
- Kept the child manifest and success event on absolute task-local paths to match the approved plan contract, but restricted the child entrypoint to canonical repo-generated task IDs (`task-<12 hex>`) before resolving work directories.

## 2026-05-03T06:05:00Z Task: persisted-execution-progress-contract-implementation
- Finalized the Wave 1 persistence shape as a standalone `TaskExecutionProgress` table with only the approved fixed fields (`task_id`, `stage_name`, `current_phase`, `phase_index`, `phase_count`, `latest_message`, `phase_started_at`, `heartbeat_at`, `phase_timings_json`, `updated_at`) so no existing table had to absorb structured ASR state.
- Kept route logic intentionally thin: `backend/app/api/routes/tasks.py` continues to delegate task detail assembly to the repository, and the repository alone decides whether `execution_progress` is omitted or serialized.
- Added explicit repository helpers `upsert_task_execution_progress()` and `clear_task_execution_progress()` as the only sanctioned persistence entrypoints for later ASR orchestration waves, instead of having subprocess code or route handlers mutate the table directly.
- Chose retry-time cleanup (`reset_index <= asr`) as the minimal stale-row safety rule for this task, because it covers retries from `asr` and earlier without broadening scope into terminal-state cleanup semantics owned by later waves.

## 2026-05-03T04:59:21Z Task: parent-owned-asr-subprocess-orchestration
- Replaced the worker's `STAGE_EXECUTORS["asr"]` binding with a dedicated `_execute_asr_subprocess()` wrapper in `backend/app/services/task_runner.py`, so the pipeline now always launches `python -m app.services.asr_child_runner <task_id>` instead of calling the in-process `transcribe_task_audio()` path from worker orchestration.
- Chose to persist streamed ASR progress from the parent by passing an `on_event` callback into `run_tracked_structured_process_group_command()` rather than duplicating subprocess parsing in the stage executor; this keeps Task 3's helper authoritative for JSONL streaming and process-group lifecycle while letting Task 4 own only the ASR-specific state projection.
- Standardized parent-side failure summaries on `exc.code` when available, so child-originated classified failures (`missing_input`, `oom`, `asr_child_failed`, etc.) survive the final task/job/stage transition logic without letting the child mutate DB terminal state directly.
## 2026-05-03T05:36:16Z Task: extend-asr-cancel-force-kill-and-stale-recovery
- Reused `app.services.task_control` as the single control boundary for Task 5 by adding `can_force_kill()`, `best_effort_kill_active_process_group()`, and `clear_execution_control()` there instead of scattering process-group checks between the route and worker layers.
- Added `/api/tasks/{task_id}/cancel` and `/api/tasks/{task_id}/force-kill` in `backend/app/api/routes/tasks.py`, with force-kill gated on both a tracked process group and a currently tracked stage (`ingest`, `media_prep`, or `asr`) so ASR only becomes killable when a real child group exists and in-process stages stay non-killable.
- Kept stale-running-job recovery targeted: only stale `asr` jobs attempt best-effort `SIGKILL` plus control-state clearing before being marked failed, which preserves the existing orphaned ingest/media-prep behavior instead of broadening stale-kill semantics across unrelated stages.

## 2026-05-03T14:01:00Z Task: frontend-asr-progress-ui
- Surfaced ASR observability as a dedicated task-detail panel built from the persisted `execution_progress` object instead of trying to stretch the existing stage timeline cards into a second transport format; the timeline remains intact, while the new panel carries phase/timing/heartbeat details explicitly.
- Overlaid the ASR timeline card from task-detail state when `status === "cancel_requested"` and the ASR stage is still running, so the frontend reflects the backend's task-detail overlay semantics even when raw `/stages` rows still say `running` with an empty summary.
- Kept the stage source preference biased toward `GET /api/tasks/{task_id}` over `/stages` in `TaskDetailPage`, because the detail payload is the only surface that can legally carry status overlays like `cancel_requested` without changing the raw stage contract.

## 2026-05-03T14:09:00Z Task: frontend-asr-progress-ui-review-followup
- Finalized ASR progress rendering with an explicit `isAsrStageActive(...)` guard that requires both an active `asr` stage row and a task-detail status of `running` or `cancel_requested` before the progress panel appears.
- Scoped inline ASR missing-model recovery UI to `failedStage?.name === "asr"` in addition to the backend recovery payload, so non-ASR failures cannot accidentally render ASR recovery controls if stale recovery data is present.

## 2026-05-03T06:23:04Z Task: focused-asr-regression-coverage
- Chose to fix the one exposed product gap in `backend/app/worker.py` instead of weakening the new regression: stale ASR recovery now clears `TaskExecutionProgress` at the same boundary where it clears execution control, preserving the original repository contract that `execution_progress` exists only for active tracked ASR execution.
- Kept Task 7 verification intentionally focused on lifecycle seams rather than broad happy-path duplication: helper-level force-kill semantics, runner-level malformed child failure finalization, stale-recovery cleanup, and terminal frontend rendering were sufficient to protect the new ASR control surface without rewriting Wave 1/2 tests.

## 2026-05-03T06:29:28Z Task: operator-and-developer-docs
- Added the detailed ASR lifecycle semantics to `docs/operator-manual*.md` instead of the user manuals, because the new behavior is operational and troubleshooting-oriented: phase timing visibility, tracked-process-group kill semantics, and status-overlay interpretation belong to operators rather than end users.
- Added a short post-startup lifecycle section to `docs/deployment-guide*.md` so deployment-facing readers can verify the new observability contract in the same document they already use for runtime checks, without turning the guide into a release note for unrelated features.
- Kept `docs/README*.md` to one-line index updates only, to avoid creating a third independently maintained explanation of `execution_progress`, `cancel_requested`, and `force-kill` behavior.
