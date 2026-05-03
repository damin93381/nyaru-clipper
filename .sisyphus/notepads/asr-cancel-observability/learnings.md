## 2026-05-03T03:45:57Z Task: session-start
ASR phase scope approved: add true interruption plus observability/timing visibility, while preserving current transcription/alignment quality and deferring CPU/GPU tuning.

## 2026-05-03T05:14:00Z Task: persisted-execution-progress-contract
- `GET /api/tasks/{task_id}` can stay backward compatible by omitting `execution_progress` entirely when no tracked row exists; existing task detail consumers continue to work without requiring null placeholders.
- SQLite round-trips stored datetimes back as naive values in this repo, so task-detail serialization must normalize persisted `phase_started_at` and `heartbeat_at` to UTC before emitting API timestamps.
- A read-only progress contract is not enough for this task: adding repository-level upsert/clear helpers makes the persistence path explicit and testable without pulling ASR subprocess orchestration into Wave 1.
- Retrying from `asr` or any earlier stage must clear persisted execution progress first, otherwise a stale ASR row can briefly resurface when the stage becomes active again.

## 2026-05-03T03:55:09Z Task: structured-streaming-helper
- Added a dedicated structured-progress subprocess helper in `backend/app/services/pipeline_support.py` instead of overloading `run_tracked_process_group_command()`, which kept the existing ingest/media-prep contract stable while introducing JSONL stdout parsing for future ASR orchestration.
- The helper proved easiest to keep parent-owned by combining reader threads for line-buffered stdout/stderr with the existing `TaskExecutionControl` heartbeat updates from the parent session; focused tests now cover progress streaming, heartbeat movement, SIGTERM→SIGKILL cancel escalation, and malformed-event classification.

## 2026-05-03T05:32:00Z Task: structured-streaming-helper-scope-repair
- Task 3 cannot depend on control-state files from other waves if its working tree must stand alone; keeping the structured helper self-sufficient required moving its focused execution-context and cancel/heartbeat state handling into `pipeline_support.py` itself for the narrowed verification pass.

## 2026-05-03T05:47:00Z Task: structured-streaming-helper-control-alignment
- Duplicating a second control table in `pipeline_support.py` was the wrong abstraction boundary; the helper layer should late-bind to the repo control contract (`app.services.task_control` plus `app.models.TaskExecutionControl`) and keep all streamed-process behavior behind that existing interface instead of shadowing it.

## 2026-05-03T04:14:41Z Task: child-runner-protocol
- The child protocol can share one WhisperX core by extracting a phase-driven `execute_asr_pipeline()` and letting the child add JSONL/stdout + manifest concerns around it.
- Pre-pipeline child failures need their original classified code preserved; otherwise missing input is easily misreported as missing model during protocol fallback handling.

## 2026-05-03T06:26:00Z Task: child-runner-protocol-implementation
- The shared ASR core needs a single true `persist` boundary: writing transcript/subtitle outputs a second time after `phase_complete` makes manifest phase state and elapsed timing drift apart, so the core should emit `persist` completion only after the one real output write finishes.
- The child runner can safely keep the plan's absolute `manifest_path` contract while still hardening direct CLI use by rejecting non-canonical task IDs before deriving `tasks/<task_id>/work` paths.

## 2026-05-03T06:05:00Z Task: persisted-execution-progress-contract-implementation
- `TaskExecutionProgress` can be introduced safely in this repo by adding a new SQLModel table only; the backend runtime already bootstraps schema with `SQLModel.metadata.create_all(...)`, so no migration layer is needed for this Wave 1 table.
- Keeping `execution_progress` omitted when no row exists preserves current task-detail consumers without forcing placeholder null handling, while still letting active ASR tasks surface a structured progress object.
- The repository is the right serialization boundary for progress rows: storing raw phase timing JSON in the table and emitting parsed `phases` from `get_task_detail()` kept the API conservative and avoided leaking persistence details into the route layer.
- SQLite still round-trips persisted aware datetimes back as naive values in these tests, so task-detail serialization must normalize `phase_started_at` and `heartbeat_at` to UTC before emitting ISO strings.
- Clearing persisted progress inside `retry_task_from_stage()` when the retry target is `asr` or any earlier stage is enough to prevent stale ASR progress from resurfacing, without pulling Wave 2 cancellation orchestration into this task.

## 2026-05-03T04:59:21Z Task: parent-owned-asr-subprocess-orchestration
- The cleanest way to make ASR progress observable during execution without reintroducing a second reader loop in `task_runner.py` was to extend the structured subprocess helper with an optional per-event callback; the parent can now persist `TaskExecutionProgress` incrementally while still reusing Task 3's JSONL parser, logging, and process-group control path.
- Parent-only terminal ownership is easiest to preserve when the ASR executor returns a `StageDirective` and publishes DB artifacts only after re-reading a verified `success` manifest; the child can emit `failure` events and write `asr-result.json`, but task/job/stage terminal state stays exclusively in `run_task_pipeline()`.
- Successful manifest publication needed to preserve the old artifact metadata shape (`alignment_raw`, `transcript_json`, `subtitle_srt` plus elapsed/model/source metadata), so the parent now derives transcript `segment_count` from the child-written transcript JSON instead of inventing a second artifact contract.

## 2026-05-03T05:36:16Z Task: extend-asr-cancel-force-kill-and-stale-recovery
- Task 5 did not need a second subprocess-control implementation: the structured helper from Task 3 already enforced the 10-second SIGTERM→SIGKILL ladder, so the missing pieces were the API/control-layer gating and stale-worker cleanup around that helper.
- Preserving the `cancel_requested` overlay without mutating raw stage rows works cleanly at task-detail serialization time: the detail payload can advertise `cancel_requested` when control flags are set, while `/stages` still reports the underlying running `asr` stage.
- Stale ASR recovery must kill before it clears control state; killing the recorded process group first and only then nulling the execution token / pgid keeps the queue-unblock path aligned with the plan’s “no fake cleanup before a real termination attempt” rule.

## 2026-05-03T05:45:15Z Task: task-5-repair
- Parent verification was right about the mismatch location: having stale-ASR pgid termination hidden inside `_mark_job_stale_failed()` was too indirect for Task 5, so the real queue-recovery path now performs the best-effort ASR pgid kill and control-row clearing in `_recover_stale_running_jobs()` before it marks the stale job failed.
- Force-kill gating also needed to be narrower than “any tracked-process-group stage”: the route-level behavior is now backed by `can_force_kill()` requiring both a live tracked pgid and an active `asr` job, while `cancel_requested` overlay behavior stays unchanged for task detail.

## 2026-05-03T14:01:00Z Task: frontend-asr-progress-ui
- Frontend compatibility is simplest when `TaskDetail` treats `execution_progress` as optional and `cancel_requested` as a task-detail status: legacy tasks keep their existing rendering path, while active ASR tasks can light up a dedicated progress panel without forcing placeholder objects.
- The timeline should not trust raw `/stages` summaries for in-flight ASR cancel states; overlaying the `asr` card summary and badge from task-detail status plus `execution_progress` avoids the misleading idle copy (`等待该阶段开始。`) that raw stage rows can still produce mid-cancel.
- Reusing the existing `panel`, `summary-strip`, `metadata-list`, and `stage-card` primitives was enough to surface ASR phase timing, heartbeat, and latest-message details without introducing a parallel UI pattern just for this feature.

## 2026-05-03T14:09:00Z Task: frontend-asr-progress-ui-review-followup
- Review feedback exposed that ASR-only affordances need one more guard than `execution_progress.stage_name === "asr"`: the frontend should also confirm the canonical `asr` stage is still actively running (with task status `running` or `cancel_requested`) before rendering the progress panel, otherwise stale backend rows could make later-stage task detail look falsely active.
- ASR recovery copy must be scoped to an actual failed ASR stage, not just the presence of `failure_recovery.stage === "asr"`; tightening that condition keeps unrelated failure panels from showing model-download guidance.

## 2026-05-03T06:23:04Z Task: focused-asr-regression-coverage
- Focused Task 7 coverage exposed one real backend hole: stale ASR worker recovery already killed the old process group and cleared execution control, but it did not clear the persisted `TaskExecutionProgress` row, which could leave inactive ASR work looking active through the task-detail contract.
- The most valuable regression split was three-layered: helper-level direct `force_kill_requested` behavior in `test_pipeline_support.py`, runner-level malformed-child integration in `test_task_runner.py`, and terminal frontend rendering in `TaskDetailPage.test.tsx` to ensure stale `execution_progress` payloads do not resurrect the ASR progress panel.
- The malformed-child regression is strongest when it asserts both storage cleanup (`execution_progress` row gone) and user-visible state (`task.status == failed` with no `execution_progress` in task detail), because helper-only protocol tests do not prove the parent leaves the task out of limbo.

## 2026-05-03T06:29:28Z Task: operator-and-developer-docs
- The docs needed to mirror the backend and frontend split between raw stage rows and task-detail overlays: the most operator-safe wording is to describe `cancel_requested` as a task-detail overlay while explicitly warning that `/stages` can still show the underlying running `asr` row during drain-down.
- The cleanest documentation boundary is stage-level flow in the operator manual plus post-startup interpretation guidance in the deployment guide, with the docs indexes only pointing readers at that lifecycle contract instead of duplicating behavior details a third time.
- This task needed an explicit non-scope statement in both languages, because the same docs already describe GPU assumptions and degraded CPU fallback; without that clarification, readers could easily misread new ASR timing visibility as a CPU or GPU tuning change.

## 2026-05-03T06:59:29Z Task: final-wave-defect-fix
- Fixed the stale-ASR-heartbeat gap by adding a lightweight periodic observer heartbeat inside , so long-running real phases keep refreshing  without changing WhisperX model, compute, or alignment behavior.
- Tightened  to require both a tracked process group and an actually running raw  job/stage, which blocks stale failed control rows from surfacing  while preserving the ASR-only scope of this phase.

## 2026-05-03T06:59:39Z Task: final-wave-defect-fix
- Fixed the stale ASR heartbeat gap by adding a lightweight periodic observer heartbeat inside _run_pipeline_phase, so long-running real phases keep refreshing execution_progress.heartbeat_at without changing WhisperX model, compute, or alignment behavior.
- Tightened can_force_kill() to require both a tracked process group and an actually running raw asr job/stage, which blocks stale failed control rows from surfacing force-kill while preserving the ASR-only scope of this phase.

## 2026-05-03T07:10:17Z Task: final-wave-cleanup-fix
- Promoted cancelled to a real frontend terminal task state by extending the typed status union, terminal-status set, and glossary label, which fixed polling cadence and status badge rendering for cancelled task detail views.
- Tightened backend cancel eligibility so request_cancel only succeeds for a truly active running task/job/stage, preventing stale control rows from making terminal tasks look cancellable.
