# Task 6 report: durable workstation events and SSE

## Changed files

- `backend/app/models.py`: adds the durable `WorkstationEvent` SQLModel.
- `backend/alembic/versions/20260712_02_workstation_events.py`: creates the event table and indexes.
- `backend/app/services/workstation_events.py`: persists public event projections, prunes old events while retaining the newest 10,000, and replays/polls events through fresh short-lived SQLite sessions.
- `backend/app/api/routes/workstation_events.py`: exposes `GET /api/v2/events` as `text/event-stream` with `Last-Event-ID` replay and heartbeat semantics.
- `backend/app/api/routes/__init__.py`: mounts the v2 events route.
- `backend/app/repositories/tasks.py`: stages task-created, task-updated, and stage-updated events in the caller transaction.
- `backend/app/services/workstation_queue.py`: stages safe queue snapshots in the same transaction as queue mutations.
- `backend/app/services/storage.py`: stages `artifact.ready` after artifact metadata is written, exposing only the public artifact-content route rather than the host path.
- `backend/tests/workstation/test_event_stream.py`: covers monotonic IDs, reconnect replay, serialized frames, heartbeats, public task/queue projection events, artifact events, and the SSE response contract.

## Verification

- RED: `backend/.venv/bin/python -m pytest tests/workstation/test_event_stream.py -q -s` initially failed because `app.services.workstation_events` did not exist.
- RED: the artifact-specific event test initially failed with no `artifact.ready` event.
- GREEN: `backend/.venv/bin/python -m pytest tests/workstation/test_event_stream.py -q -s` — `5 passed`.
- `backend/.venv/bin/python -m pytest tests/workstation/test_event_stream.py tests/test_task_runner.py tests/test_task_execution_progress_repo.py tests/test_tasks_api.py -q -s` — `33 passed`, with one existing Hugging Face deprecation warning.
- `PATH=/home/drm/workfile/nyaru-clipper/backend/.venv/bin:$PATH backend/.venv/bin/python -m pytest tests/workstation/test_queue_service.py tests/workstation/test_queue_api.py tests/workstation/test_task_create_api.py tests/test_worker_runtime_warnings.py -q -s` — `21 passed`.
- `backend/.venv/bin/python -m compileall -q backend/app backend/tests/workstation/test_event_stream.py` — passed.
- `git diff --check` — passed.

## Concerns

- The shared venv does not include Ruff, so `python -m ruff check` could not run. Compilation and the requested regression suites passed.
- The worker compatibility suite invokes bare `python` in one stale-process fixture; adding the required shared venv `bin` directory to `PATH` was necessary for that fixture on this host. No source change was made for the environment issue.

## Review follow-up

### Fixed findings

- The v2 task-creation route now stages `task.created` with the task creation transaction.
- Normal task-runner checkpoints now stage safe `task.updated` and `stage.updated` projections before committing; worker claim, completion, and stale-job recovery transitions do the same.
- Event replay now reads ordered pages of 100 rows, converts each page to frames before its short-lived session closes, and advances the cursor while yielding the page.

### Added regression coverage

- The v2 HTTP creation route commits a public `task.created` event.
- Runner stage checkpoints and worker claim/complete transitions publish public task/stage events.
- Replay of five events with a two-row test page uses three ordered, limited queries without duplicate frames.

### Verification

- RED: `backend/.venv/bin/python -m pytest tests/workstation/test_event_stream.py -q -s` — three lifecycle-event assertions failed before the fix.
- RED: `backend/.venv/bin/python -m pytest tests/workstation/test_event_stream.py::test_event_replay_reads_bounded_ordered_pages -q -s` — the prior unbounded replay issued one query rather than three limited pages.
- GREEN: `backend/.venv/bin/python -m pytest tests/workstation/test_event_stream.py -q -s` — `9 passed`.
- `PATH=/home/drm/workfile/nyaru-clipper/backend/.venv/bin:$PATH backend/.venv/bin/python -m pytest tests/workstation/test_event_stream.py tests/workstation/test_queue_service.py tests/workstation/test_queue_api.py tests/workstation/test_task_create_api.py tests/test_task_runner.py tests/test_task_execution_progress_repo.py tests/test_tasks_api.py tests/test_worker_runtime_warnings.py -q -s` — `58 passed`, with one existing Hugging Face deprecation warning.
- `backend/.venv/bin/python -m compileall -q backend/app backend/tests/workstation/test_event_stream.py` — passed.
- `git diff --check` — passed.

### Remaining concern

- The stale-process worker fixture still requires the venv `bin` directory on `PATH` because it invokes bare `python`; this is an existing test-environment assumption, not a source change.

## Final P1 follow-up: task-library lifecycle projections

### Root cause and fix

- The v2 library lifecycle service mutated metadata and archive state, and removed inactive tasks, without staging matching durable task projections. For deletions, staging a tombstone before the queue helper was also unsafe: `delete_queue_entry` acquires SQLite's immediate transaction when needed, which discarded the earlier event transaction.
- Metadata PATCH, archive, and unarchive now stage public `task.updated` projections in their caller transaction. Deletion stages the safe `task.deleted` tombstone (`task_id` only) after queue deletion has acquired the transaction and immediately before deleting the task row. Existing `queue.updated` behavior remains unchanged.

### Regression coverage

- `backend/tests/workstation/test_task_library_api.py` drives the v2 PATCH and bulk archive, unarchive, and delete endpoints. It asserts the three update projections and deletion tombstone in order, while verifying that the fixture's host source path never appears in a durable event payload.

### Verification

- RED: `PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/workstation/test_task_library_api.py::test_task_library_lifecycle_mutations_publish_public_events -q -s` — failed with no durable lifecycle events.
- GREEN: same focused command — `1 passed in 4.38s`.
- Compatibility: `PATH=/home/drm/workfile/nyaru-clipper/backend/.venv/bin:$PATH PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/workstation/test_event_stream.py backend/tests/workstation/test_task_library_api.py backend/tests/workstation/test_task_library_repository.py backend/tests/workstation/test_queue_service.py backend/tests/workstation/test_queue_api.py backend/tests/workstation/test_task_create_api.py backend/tests/test_tasks_api.py -q -s` — `58 passed, 1 warning in 66.70s`; the warning is the existing Hugging Face `local_dir_use_symlinks` deprecation.
- `PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m compileall -q backend/app/services/task_library_lifecycle.py backend/tests/workstation/test_task_library_api.py` — passed.
- `git diff --check` — passed.

## P1 follow-up: manual export event projections

### Root cause and fix

- `pipeline_support.set_stage_status` staged the mutated `TaskStage`, and marked its `Task` failed when appropriate, but did not stage their durable public event projections. This affected the v1 manual clip-export route, whose failure path commits inside `clip_export` before returning an HTTP 400.
- `set_stage_status` now stages `stage.updated` after the stage mutation. When it changes a task status to `failed`, it also stages `task.updated` in the same transaction before the existing caller-controlled commit. No v1 route or service commit behavior changed.

### Regression coverage

- `backend/tests/test_clip_export_api.py` now drives the actual `POST /api/tasks/{task_id}/clips` route and asserts a durable `stage.updated` projection for a successful manual export.
- The same route-level coverage simulates ffmpeg failure and asserts the internally committed `task.updated` (`failed`) and `stage.updated` (`export`, `failed`) projections.

### Verification

- RED: `PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/test_clip_export_api.py::test_post_clips_persists_public_stage_event_after_successful_manual_export backend/tests/test_clip_export_api.py::test_post_clips_persists_task_and_stage_events_after_failed_manual_export -q -s` — `2 failed`; both expected durable manual-export projections were absent.
- GREEN: same focused command — `2 passed in 4.13s`.
- Focused event/export/pipeline: `PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/workstation/test_event_stream.py backend/tests/test_clip_export.py backend/tests/test_clip_export_api.py backend/tests/test_pipeline_support.py backend/tests/test_task_runner.py -q -s` — `32 passed in 30.63s`.
- Compatibility: `PATH=/home/drm/workfile/nyaru-clipper/backend/.venv/bin:$PATH PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/workstation/test_event_stream.py backend/tests/workstation/test_queue_service.py backend/tests/workstation/test_queue_api.py backend/tests/workstation/test_task_create_api.py backend/tests/test_clip_export.py backend/tests/test_clip_export_api.py backend/tests/test_task_runner.py backend/tests/test_pipeline_support.py backend/tests/test_task_execution_progress_repo.py backend/tests/test_tasks_api.py backend/tests/test_worker_runtime_warnings.py -q -s` — `71 passed in 58.46s`.
- `PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m compileall -q backend/app backend/tests/test_clip_export_api.py` — passed.
- `git diff --check` — passed.

## Final review follow-up

### Fixed findings

- V2 task creation now passes its requested priority into `enqueue_task`, so its single durable `queue.updated` snapshot is staged after the final priority rather than exposing a stale default-priority projection.
- Cancellation finalization now stages safe `task.updated` and, when the active stage becomes cancelled, `stage.updated` in the same transaction. The two early runner cancellation returns now commit that transaction before token cleanup can roll it back. The existing stage-boundary and tracked-process cancellation commits retain their ordering.

### Added regression coverage

- The v2 creation event test requests priority 7 and asserts exactly one final queue event with priority 7.
- The runner cancellation test starts from a claimed running stage, requests cancellation, and asserts the persisted cancelled task and stage events after the runner returns.

### Verification

- RED: `PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/workstation/test_event_stream.py::test_v2_task_creation_stages_a_public_created_event backend/tests/workstation/test_event_stream.py::test_runner_cancellation_commits_public_task_and_stage_events -q -s` — both failures reproduced: event priority was 0 instead of 7, and early cancellation had no finalization events.
- GREEN: the same focused command — `2 passed in 3.36s`.
- `PATH=/home/drm/workfile/nyaru-clipper/backend/.venv/bin:$PATH PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/workstation/test_event_stream.py backend/tests/workstation/test_queue_service.py backend/tests/workstation/test_queue_api.py backend/tests/workstation/test_task_create_api.py backend/tests/test_task_runner.py backend/tests/test_pipeline_support.py backend/tests/test_task_execution_progress_repo.py backend/tests/test_tasks_api.py backend/tests/test_worker_runtime_warnings.py -q -s` — `65 passed, 1 warning in 73.87s`; the warning is the existing Hugging Face `local_dir_use_symlinks` deprecation.
- Manual API QA: a fresh Uvicorn server accepted a priority-7 `POST /api/v2/tasks`; bounded `/api/v2/events` replay emitted one `queue.updated` frame at priority 7 before `task.created`.
- `PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m compileall -q backend/app backend/tests/workstation/test_event_stream.py` — passed.
- `git diff --check` — passed.

## P1 follow-up: preserve runner checkpoint state during control reads

### Root cause and fix

- `get_control_requests` refreshed cancellation flags by expiring every object in the runner's caller session. If the runner had just marked a `TaskStage` successful but had not checkpointed it yet, that expiration discarded the dirty stage and later reads could reload the previous `pending` or `running` state, producing a stale persisted stage or `stage.updated` projection.
- The control lookup now uses an isolated short-lived SQLite session. It still observes committed cancellation and force-kill requests from other sessions, while it leaves the runner transaction and its staged state/event mutations untouched.

### Regression coverage

- `backend/tests/test_task_control_runner_state.py` directly proves a no-cancellation control read preserves a dirty successful stage checkpoint.
- The same dedicated runner regression binds a real execution token, completes the normal pipeline without cancellation, and asserts both the persisted ingest stage and its durable `stage.updated` payload are `success`.
- Existing runner cancellation coverage remains in `backend/tests/test_task_runner.py::test_run_task_pipeline_finalizes_stage_boundary_cancel_without_starting_next_stage`.

### Verification

- RED: `PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/test_task_runner.py::test_control_read_preserves_dirty_runner_stage_checkpoint_when_no_cancel -q -s` — failed with `assert 'pending' == 'success'` before the isolated read.
- GREEN: `PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/test_task_control_runner_state.py backend/tests/test_task_runner.py::test_run_task_pipeline_finalizes_stage_boundary_cancel_without_starting_next_stage -q -s` — `3 passed in 3.37s`.
- Focused event/runner/control/progress: `PATH=/home/drm/workfile/nyaru-clipper/backend/.venv/bin:$PATH PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/workstation/test_event_stream.py backend/tests/test_task_runner.py backend/tests/test_pipeline_support.py backend/tests/test_task_execution_progress_repo.py -q -s` — `29 passed in 26.77s`.
- Compatibility: `PATH=/home/drm/workfile/nyaru-clipper/backend/.venv/bin:$PATH PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m pytest backend/tests/workstation/test_event_stream.py backend/tests/workstation/test_queue_service.py backend/tests/workstation/test_queue_api.py backend/tests/workstation/test_task_create_api.py backend/tests/test_task_control_runner_state.py backend/tests/test_task_runner.py backend/tests/test_pipeline_support.py backend/tests/test_task_execution_progress_repo.py backend/tests/test_tasks_api.py backend/tests/test_worker_runtime_warnings.py -q -s` — `67 passed, 1 existing Hugging Face deprecation warning in 83.76s`.
- `PYTHONPATH=backend /home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m compileall -q backend/app/services/task_control.py backend/tests/test_task_control_runner_state.py` — passed.
- `git diff --check` — passed.
