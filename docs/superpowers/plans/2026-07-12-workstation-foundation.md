# Workstation Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the MVP shell with a migration-safe desktop workstation foundation containing a scalable task library, manually ordered single-GPU queue, Bilibili/local-file task creation, real-time task overview, and visually coherent access to all current review/export capabilities.

**Architecture:** Add an additive `/api/v2` contract and Alembic-managed domain tables while keeping the current API operational during migration. Build the new React route tree under `/workstation` with generated OpenAPI types, a semantic design system, REST snapshots plus SSE invalidation, and feature-parity adapters for the current transcript/highlight/export artifacts. Switch the default route only after backend, frontend, E2E, accessibility, and visual gates pass.

**Tech Stack:** Python 3.11, FastAPI, SQLModel, Alembic, SQLite FTS5, Pydantic v2, React 18, TypeScript 5.6, React Router 7, TanStack Query 5, TanStack Table 8, dnd-kit, Radix primitives, openapi-fetch, openapi-typescript, Vitest, Playwright.

## Global Constraints

- Preserve all unrelated dirty work; implementation starts in an isolated worktree created from the intended integrated baseline.
- The runtime remains single-user, trusted-LAN, desktop-only, and limited to one active GPU-bound pipeline job.
- Backend Python remains `>=3.11,<3.12`; frontend Node remains `>=20` with pnpm `10.33.2`.
- Support viewport widths of 1280, 1440, and 1920 px; no mobile layout is part of this plan.
- Preserve existing task IDs, artifact paths, SQLite data, cancellation behavior, retries, subtitle viewing, highlight confirmation, and clip export.
- Add new API behavior under `/api/v2`; keep current `/api/tasks` routes working until the final cutover task.
- Do not hand-edit generated `backend/requirements*.txt`; regenerate them with `./scripts/export_backend_requirements.sh`.
- Keep backend canonical stage names unchanged.
- No external font CDN, model download, live Bilibili call, or GPU dependency is permitted in automated tests.
- No placeholder navigation items or controls may ship.
- Every behavior task follows red-green-refactor and ends with its own commit.

---

## Locked file structure

### Backend

- `backend/app/models.py`: legacy tables plus additive workstation domain tables.
- `backend/app/db_migrations.py`: Alembic configuration and programmatic upgrade entrypoint.
- `backend/alembic/`: migration environment and versioned schema changes.
- `backend/app/api/schemas/workstation.py`: v2 request/response models only.
- `backend/app/repositories/workstation.py`: task-library queries and detail projections.
- `backend/app/services/workstation_queue.py`: queue ordering, revision checks, and worker claims.
- `backend/app/services/source_catalog.py`: Bilibili inspection and trusted local-root browsing.
- `backend/app/services/workstation_events.py`: durable event IDs, replay, SSE framing, and bounded database polling.
- `backend/app/api/routes/workstation_*.py`: thin v2 HTTP facades grouped by task, queue, source, and event responsibility.
- `backend/tests/workstation/`: focused v2 model, migration, repository, route, queue, source, and SSE tests.

### Frontend

- `DESIGN.md`: design contract and primitive acceptance matrix.
- `web/src/generated/api-schema.ts`: generated OpenAPI types; never hand-edit.
- `web/src/workstation/api/`: typed v2 transport, SSE client, and query keys.
- `web/src/workstation/design/`: tokens, global rules, and primitive showcase.
- `web/src/workstation/components/`: reusable shell, table, status, progress, overlay, and form primitives.
- `web/src/workstation/features/`: task-library, queue, task-create, and task-overview feature boundaries.
- `web/src/workstation/routes/`: route-level composition only.
- `web/src/workstation/testing/`: typed fixture builders and MSW-free fetch/EventSource harnesses.

---

### Task 1: Alembic baseline and additive workstation domain

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/services/storage.py`
- Create: `backend/app/db_migrations.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/20260712_01_workstation_foundation.py`
- Create: `backend/tests/workstation/test_domain_migration.py`
- Modify: `backend/tests/test_schema_migration.py`

**Interfaces:**
- Produces: `upgrade_database(database_url: str | None = None) -> None`
- Produces: `backfill_workstation_metadata(session: Session, tasks_root: Path) -> None`
- Produces SQLModel tables: `MediaSource`, `TaskTag`, `TaskTagLink`, `QueueState`, `QueueEntry`, `PipelineRun`, `StageRun`
- Preserves: `Task`, `TaskJob`, `TaskStage`, and all existing task IDs

- [ ] **Step 1: Add failing migration tests**

Write tests that create the current pre-v2 SQLite schema, insert one task/job/seven stages, call `upgrade_database()`, and assert:

```python
assert migrated_task.id == legacy_task_id
assert media_source.task_id == legacy_task_id
assert media_source.kind == "bilibili"
assert queue_entry.task_id == legacy_task_id
assert queue_entry.state in {"queued", "running", "finished"}
assert queue_state.id == 1
assert queue_state.revision >= 1
assert pipeline_run.task_id == legacy_task_id
assert [item.name for item in stage_runs] == CANONICAL_STAGES
assert migrated_task.title
assert migrated_task.storage_bytes == expected_task_directory_size
```

Also call `upgrade_database()` twice and assert the second call is a no-op.

- [ ] **Step 2: Verify migration tests fail**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_domain_migration.py tests/test_schema_migration.py -q
```

Expected: import failure for `app.db_migrations` or missing workstation tables.

- [ ] **Step 3: Add Alembic and domain models**

Add `alembic>=1.14.0,<2.0.0` to backend dependencies. Extend `Task` with `title: str | None`, `archived_at: datetime | None`, and `storage_bytes: int = 0`. Define these stable tables:

```python
class MediaSource(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(unique=True, index=True, foreign_key="task.id")
    kind: str = Field(index=True)  # bilibili | local
    locator: str
    display_name: str | None = None
    source_video_id: str | None = Field(default=None, index=True)
    import_mode: str = "managed"  # managed | reference
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)

class QueueEntry(SQLModel, table=True):
    task_id: str = Field(primary_key=True, foreign_key="task.id")
    position: int = Field(index=True)
    priority: int = Field(default=0, index=True)
    state: str = Field(default="queued", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

class QueueState(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    revision: int = Field(default=1)
    updated_at: datetime = Field(default_factory=utc_now)

class PipelineRun(SQLModel, table=True):
    id: str = Field(primary_key=True)
    task_id: str = Field(index=True, foreign_key="task.id")
    status: str = Field(index=True)
    trigger: str = "create"
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

class StageRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, foreign_key="pipelinerun.id")
    name: str = Field(index=True)
    status: str = Field(index=True)
    summary: str | None = None
    failure_code: str | None = Field(default=None, index=True)
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
```

Define `TaskTag(name primary key, created_at)` and `TaskTagLink(task_id, tag_name)` with a composite unique constraint in the migration.

- [ ] **Step 4: Implement and run migrations**

`upgrade_database()` must build an Alembic `Config` from `backend/alembic.ini`, override `sqlalchemy.url`, and call `command.upgrade(config, "head")`. Update `init_db()` to invoke this function before the temporary `SQLModel.metadata.create_all()` compatibility call.

The migration creates additive tables, inserts the singleton `QueueState(id=1)`, backfills `MediaSource`, `QueueEntry`, one `PipelineRun`, and seven `StageRun` rows per current task, and leaves legacy tables intact. For SQLite it also creates an FTS5 `task_search` virtual table and insert/update/delete triggers for title and source identity. On the first upgrade only, `upgrade_database()` calls a pure `backfill_workstation_metadata(session, tasks_root)` helper that derives a usable title from `source-metadata.json`/video ID and sums file sizes under that task's managed directory. `persist_artifact_metadata()` increments or recomputes `Task.storage_bytes` after subsequent artifact writes.

- [ ] **Step 5: Run migration and existing schema tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_domain_migration.py tests/test_schema_migration.py tests/test_smoke.py -q
```

Expected: all pass.

- [ ] **Step 6: Regenerate requirements and commit**

```bash
./scripts/export_backend_requirements.sh
./scripts/export_backend_requirements.sh --check
git add backend/pyproject.toml backend/uv.lock backend/requirements*.txt backend/alembic.ini backend/alembic backend/app/models.py backend/app/db.py backend/app/db_migrations.py backend/app/services/storage.py backend/tests/workstation/test_domain_migration.py backend/tests/test_schema_migration.py
git commit -m "feat(db): add workstation domain migrations"
```

### Task 2: Versioned workstation schemas and task-library repository

**Files:**
- Create: `backend/app/api/schemas/__init__.py`
- Create: `backend/app/api/schemas/workstation.py`
- Create: `backend/app/repositories/workstation.py`
- Create: `backend/tests/workstation/test_task_library_repository.py`

**Interfaces:**
- Produces: `TaskListQuery`, `TaskListItem`, `TaskListPage`, `TaskLibrarySummary`, `TaskOverview`
- Produces: `list_workstation_tasks(session, query) -> TaskListPage`
- Produces: `get_task_library_summary(session) -> TaskLibrarySummary`
- Produces: `get_workstation_task_overview(session, task_id) -> TaskOverview | None`

- [ ] **Step 1: Write failing repository tests**

Seed 1,025 tasks with mixed statuses, source kinds, tags, and timestamps. Assert:

```python
page = list_workstation_tasks(
    session,
    TaskListQuery(query="夏日", statuses=["running", "failed"], page=2, page_size=50),
)
assert page.page == 2
assert page.page_size == 50
assert page.total >= len(page.items)
assert all("夏日" in item.title for item in page.items)
assert all(item.status in {"running", "failed"} for item in page.items)
assert len(page.items) <= 50
```

Assert stable tie-breaking by `Task.updated_at DESC, Task.id DESC`, tag filtering, archived exclusion by default, and summary counts.

- [ ] **Step 2: Verify repository tests fail**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_task_library_repository.py -q
```

Expected: missing repository and schema imports.

- [ ] **Step 3: Define transport schemas**

Use Pydantic discriminated models and literal statuses. The page contract is:

```python
class TaskListPage(BaseModel):
    items: list[TaskListItem]
    page: int
    page_size: int
    total: int
    page_count: int

class TaskLibrarySummary(BaseModel):
    active: int
    queued: int
    review_required: int
    failed: int
    archived: int
    storage_bytes: int
```

`TaskListItem` contains `task_id`, `title`, `source_kind`, `source_label`, `status`, `current_stage`, `progress_percent`, `tags`, `storage_bytes`, and ISO timestamps.

`TaskOverview` contains that same task identity plus `pipeline_run_id`, ordered `stages`, `execution_progress`, `artifact_readiness`, `artifacts`, `safe_logs`, and backend-authored `recovery_actions`. Pending tasks without a started `PipelineRun` receive seven planned stage records from their legacy pending stages.

- [ ] **Step 4: Implement bounded server-side queries**

Clamp `page_size` to 100. Escape LIKE wildcards. Filter and count in SQL; never load all tasks and slice in Python. Use SQLite FTS5 when available and a deterministic escaped-LIKE fallback for test/in-memory databases.

- [ ] **Step 5: Run repository tests**

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_task_library_repository.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas backend/app/repositories/workstation.py backend/tests/workstation/test_task_library_repository.py
git commit -m "feat(api): add workstation task projections"
```

### Task 3: Task-library v2 HTTP API and bulk mutations

**Files:**
- Create: `backend/app/api/routes/workstation_tasks.py`
- Modify: `backend/app/api/routes/__init__.py`
- Create: `backend/tests/workstation/test_task_library_api.py`

**Interfaces:**
- Produces: `GET /api/v2/tasks`
- Produces: `GET /api/v2/tasks/summary`
- Produces: `GET /api/v2/tasks/{task_id}`
- Produces: `PATCH /api/v2/tasks/{task_id}`
- Produces: `POST /api/v2/tasks/bulk`

- [ ] **Step 1: Write failing route tests**

Assert query parsing, 100-item page-size cap, 404 behavior, and this bulk contract:

```json
{
  "operation": "archive",
  "task_ids": ["task-a", "task-missing"]
}
```

returns HTTP 200 with:

```json
{
  "results": [
    {"task_id": "task-a", "status": "success", "message": null},
    {"task_id": "task-missing", "status": "not_found", "message": "Task not found"}
  ]
}
```

Test tag replacement, unarchive, and rejection of deletion for an actively running task.

- [ ] **Step 2: Run tests and confirm failure**

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_task_library_api.py -q
```

Expected: 404 for unregistered `/api/v2/tasks`.

- [ ] **Step 3: Implement the v2 task router**

Create one `APIRouter(prefix="/v2/tasks", tags=["workstation-tasks"])`. Route handlers validate transport input, call repository/service functions, commit once per mutation, and return per-task bulk results.

- [ ] **Step 4: Register routes and run regression tests**

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_task_library_api.py tests/test_tasks_api.py tests/test_retry_api.py -q
```

Expected: all pass; current v1 routes remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/workstation_tasks.py backend/app/api/routes/__init__.py backend/tests/workstation/test_task_library_api.py
git commit -m "feat(api): expose workstation task library"
```

### Task 4: Revisioned queue service, API, and worker claim

**Files:**
- Create: `backend/app/services/workstation_queue.py`
- Create: `backend/app/services/workstation_runs.py`
- Create: `backend/app/api/routes/workstation_queue.py`
- Modify: `backend/app/api/routes/__init__.py`
- Modify: `backend/app/worker.py`
- Modify: `backend/app/services/task_runner.py`
- Create: `backend/tests/workstation/test_queue_service.py`
- Create: `backend/tests/workstation/test_queue_api.py`
- Create: `backend/tests/workstation/test_run_projection.py`
- Modify: `backend/tests/test_worker_runtime_warnings.py`

**Interfaces:**
- Produces: `QueueSnapshot(revision: int, active: QueueItem | None, queued: list[QueueItem], paused: list[QueueItem])`
- Produces: `reorder_queue(session, ordered_task_ids: list[str], expected_revision: int) -> QueueSnapshot`
- Produces: `set_queue_state(session, task_id: str, state: Literal["queued", "paused"]) -> QueueSnapshot`
- Produces: `claim_next_queue_entry(session) -> QueueEntry | None`
- Produces: `create_pipeline_run(session, task_id: str, trigger: str) -> PipelineRun`
- Produces: `get_pending_pipeline_run(session, task_id: str) -> PipelineRun | None`
- Produces: `sync_stage_run(session, run_id: str, legacy_stage: TaskStage) -> StageRun`
- Produces: `GET /api/v2/queue`, `PUT /api/v2/queue/order`, `PATCH /api/v2/queue/{task_id}`

- [ ] **Step 1: Write failing queue invariants**

Tests must prove:

```python
snapshot = reorder_queue(session, ["task-c", "task-a", "task-b"], expected_revision=4)
assert [item.task_id for item in snapshot.queued] == ["task-c", "task-a", "task-b"]
assert snapshot.revision == 5
```

Also assert duplicate IDs, missing queued IDs, active-task moves, and stale revisions raise typed `QueueConflict(current_snapshot)`; paused tasks cannot be claimed; only one running GPU entry exists after concurrent claim attempts.

Write run-projection tests proving a pending run is reused when the worker starts, every legacy stage transition is mirrored, and retry creates a new run while preserving the previous failed run.

- [ ] **Step 2: Verify queue tests fail**

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_queue_service.py tests/workstation/test_queue_api.py -q
```

Expected: missing service/router.

- [ ] **Step 3: Implement transactional queue operations**

Normalize positions to consecutive integers after every mutation. Increment `QueueState.revision` once in the same transaction. A stale reorder returns HTTP 409 with the authoritative `QueueSnapshot`. Use SQLite `BEGIN IMMEDIATE` around claim/reorder mutations so two worker or API threads cannot accept the same revision or claim two GPU jobs.

- [ ] **Step 4: Adapt worker claim**

`claim_next_job()` must first claim `QueueEntry` ordered by `priority DESC, position ASC, created_at ASC`, then update the matching legacy `TaskJob` during the compatibility period. Completion removes or marks the queue entry `finished` and preserves stale-job recovery.

`run_task_pipeline()` reuses the pending `PipelineRun` created with the queue entry, or creates one only for legacy tasks that lack a pending run, then calls `sync_stage_run()` after each legacy `TaskStage` transition. Retry creates a fresh pending run before requeueing. The v2 projection reads `PipelineRun/StageRun`; v1 continues reading legacy stages. Add tests proving success, failure, cancellation, and retry create accurate run history without changing v1 responses.

- [ ] **Step 5: Run queue and worker tests**

```bash
cd backend
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tests/workstation/test_queue_service.py tests/workstation/test_queue_api.py tests/workstation/test_run_projection.py tests/test_worker_runtime_warnings.py tests/test_task_runner.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workstation_queue.py backend/app/services/workstation_runs.py backend/app/api/routes/workstation_queue.py backend/app/api/routes/__init__.py backend/app/worker.py backend/app/services/task_runner.py backend/tests/workstation/test_queue_service.py backend/tests/workstation/test_queue_api.py backend/tests/workstation/test_run_projection.py backend/tests/test_worker_runtime_warnings.py
git commit -m "feat(queue): add manual workstation scheduling"
```

### Task 5: Bilibili inspection, trusted local catalog, and v2 task creation

**Files:**
- Modify: `backend/app/settings.py`
- Create: `backend/app/services/source_catalog.py`
- Create: `backend/app/api/routes/workstation_sources.py`
- Modify: `backend/app/api/routes/workstation_tasks.py`
- Modify: `backend/app/api/routes/__init__.py`
- Create: `backend/tests/workstation/test_source_catalog.py`
- Create: `backend/tests/workstation/test_task_create_api.py`

**Interfaces:**
- Produces: `APP_LOCAL_IMPORT_ROOTS` as comma-separated absolute directories
- Produces: `list_local_entries(root_id: str, relative_path: str) -> LocalDirectoryListing`
- Produces: `inspect_bilibili_source(url: str) -> SourceInspection`
- Produces: `POST /api/v2/sources/bilibili/inspect`
- Produces: `GET /api/v2/sources/local`
- Produces: `GET /api/v2/processing-profiles`
- Produces: `POST /api/v2/tasks` with a discriminated `source.kind`

- [ ] **Step 1: Write failing containment and creation tests**

Create a temporary trusted root containing MP4, MKV, a directory, a symlink leaving the root, and a text file. Assert only supported media and safe directories appear. Assert `../`, absolute-path injection, and escaping symlinks return HTTP 400.

Test both creation payloads:

```json
{"source":{"kind":"bilibili","url":"https://www.bilibili.com/video/BV1abc"},"profile_id":"standard","priority":10}
```

```json
{"source":{"kind":"local","root_id":"media","relative_path":"vod/example.mp4","import_mode":"reference"},"profile_id":"standard","priority":0}
```

- [ ] **Step 2: Verify source tests fail**

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_source_catalog.py tests/workstation/test_task_create_api.py -q
```

Expected: missing endpoints and settings.

- [ ] **Step 3: Implement trusted-root catalog**

Resolve every candidate with `Path.resolve(strict=True)`, require `candidate.is_relative_to(root)`, reject symlinks that resolve outside the root, and return only directories plus `.mp4`, `.mkv`, `.mov`, `.webm`, and `.flv` files. Root IDs are stable hashes of configured absolute roots; responses expose display names and relative paths, not arbitrary host paths.

- [ ] **Step 4: Implement source inspection and creation**

Bilibili inspection reuses URL normalization and downloader metadata parsing behind a stub-friendly subprocess boundary. Task creation writes `Task`, `MediaSource`, seven legacy stages, one pipeline run with seven stage runs, `TaskJob`, and `QueueEntry` in one transaction.

`standard` is the only first-phase processing profile and maps to all seven canonical stages. No decorative per-stage toggles are returned.

- [ ] **Step 5: Run source, creation, and legacy creation tests**

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_source_catalog.py tests/workstation/test_task_create_api.py tests/test_tasks_api.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/settings.py backend/app/services/source_catalog.py backend/app/api/routes/workstation_sources.py backend/app/api/routes/workstation_tasks.py backend/app/api/routes/__init__.py backend/tests/workstation/test_source_catalog.py backend/tests/workstation/test_task_create_api.py
git commit -m "feat(tasks): support inspected workstation sources"
```

### Task 6: Durable workstation events and SSE endpoint

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/20260712_02_workstation_events.py`
- Create: `backend/app/services/workstation_events.py`
- Create: `backend/app/api/routes/workstation_events.py`
- Modify: `backend/app/api/routes/__init__.py`
- Modify: `backend/app/repositories/tasks.py`
- Modify: `backend/app/services/workstation_queue.py`
- Create: `backend/tests/workstation/test_event_stream.py`

**Interfaces:**
- Produces: `WorkstationEvent(id, event_type, entity_id, payload_json, created_at)`
- Produces: `publish_event(session, event_type: str, entity_id: str, payload: dict[str, Any]) -> WorkstationEvent`
- Produces: `iter_events(last_event_id: int | None, heartbeat_seconds: float) -> AsyncIterator[str]`
- Produces: `GET /api/v2/events` as `text/event-stream`

- [ ] **Step 1: Write failing event tests**

Assert monotonic IDs, replay after `Last-Event-ID`, heartbeat comments, and serialized frames:

```text
id: 42
event: task.updated
data: {"task_id":"task-a","status":"running"}

```

Assert a reconnect after event 42 receives 43 onward without duplicates.

- [ ] **Step 2: Verify event tests fail**

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_event_stream.py -q
```

Expected: missing event model/service.

- [ ] **Step 3: Implement event persistence and fan-out**

Persist events in the same transaction as the state change. On connection, query events greater than `Last-Event-ID` every 500 ms using a fresh short-lived session, yielding rows in ascending ID order. Emit a `: heartbeat\n\n` comment every 15 seconds of inactivity. Prune events older than seven days while retaining the newest 10,000. This database-polling loop works across API/worker processes and requires no cross-thread event-loop notification.

- [ ] **Step 4: Publish events at repository boundaries**

Publish `task.created`, `task.updated`, `queue.updated`, `stage.updated`, and `artifact.ready` only after the corresponding model mutation has been added to the session. The request/worker transaction commits data and event together.

- [ ] **Step 5: Run event and pipeline regression tests**

```bash
cd backend
.venv/bin/python -m pytest tests/workstation/test_event_stream.py tests/test_task_runner.py tests/test_task_execution_progress_repo.py tests/test_tasks_api.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/20260712_02_workstation_events.py backend/app/services/workstation_events.py backend/app/api/routes/workstation_events.py backend/app/api/routes/__init__.py backend/app/repositories/tasks.py backend/app/services/workstation_queue.py backend/tests/workstation/test_event_stream.py
git commit -m "feat(api): stream workstation state events"
```

### Task 7: Deterministic OpenAPI export and generated TypeScript contract

**Files:**
- Modify: `web/package.json`
- Modify: `web/pnpm-lock.yaml`
- Create: `scripts/export_openapi_schema.py`
- Create: `web/openapi.json`
- Create: `web/src/generated/api-schema.ts`
- Create: `web/src/workstation/api/client.ts`
- Create: `web/src/workstation/api/queryKeys.ts`
- Create: `web/src/workstation/api/__tests__/client.test.ts`
- Modify: `backend/tests/test_requirements_export.py`

**Interfaces:**
- Produces: `pnpm --dir web api:generate`
- Produces: `workstationClient` from `openapi-fetch`
- Produces: stable `workstationKeys` query-key factory

- [ ] **Step 1: Add failing generation and client tests**

Assert `api:generate` exits cleanly and a typed client request to `/api/v2/tasks` uses query parameters without handwritten response casts. Add a repository check that rerunning generation produces no diff.

- [ ] **Step 2: Install pinned client tooling**

```bash
pnpm --dir web add openapi-fetch@^0.14.0
pnpm --dir web add -D openapi-typescript@^7.8.0
```

Add:

```json
"api:export": "../backend/.venv/bin/python ../scripts/export_openapi_schema.py --output openapi.json",
"api:generate": "pnpm api:export && openapi-typescript openapi.json -o src/generated/api-schema.ts"
```

- [ ] **Step 3: Implement deterministic schema export**

The script resolves the repository root from `__file__`, prepends `<repo>/backend` to `sys.path`, imports `app.main.app`, calls `app.openapi()`, recursively sorts object keys, and writes UTF-8 JSON with two-space indentation and one trailing newline. It accepts only an explicit `--output` path.

- [ ] **Step 4: Generate contract and implement client**

```typescript
import createClient from "openapi-fetch";
import type { paths } from "../../generated/api-schema";

export const workstationClient = createClient<paths>({
  baseUrl: (import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api").replace(/\/$/, ""),
});
```

The query-key factory exposes `all`, `summary`, `list(filters)`, `detail(taskId)`, and `queue`.

- [ ] **Step 5: Verify generated contract**

```bash
pnpm --dir web api:generate
git add web/openapi.json web/src/generated/api-schema.ts
pnpm --dir web api:generate
git diff --exit-code -- web/openapi.json web/src/generated/api-schema.ts
pnpm --dir web test --run src/workstation/api/__tests__/client.test.ts
```

Expected: no generation diff and client tests pass.

- [ ] **Step 6: Commit**

```bash
git add web/package.json web/pnpm-lock.yaml scripts/export_openapi_schema.py web/openapi.json web/src/generated/api-schema.ts web/src/workstation/api
git commit -m "build(web): generate workstation api contract"
```

### Task 8: DESIGN.md, semantic tokens, and primitive showcase

**Files:**
- Create: `DESIGN.md`
- Modify: `web/package.json`
- Modify: `web/pnpm-lock.yaml`
- Create: `web/src/workstation/design/tokens.css`
- Create: `web/src/workstation/design/global.css`
- Create: `web/src/workstation/design/primitives.css`
- Create: `web/src/workstation/routes/PrimitiveShowcasePage.tsx`
- Create: `web/src/workstation/routes/__tests__/PrimitiveShowcasePage.test.tsx`

**Interfaces:**
- Produces semantic CSS tokens prefixed `--ny-`
- Produces `PrimitiveShowcasePage` covering every primitive state before product pages use them

- [ ] **Step 1: Write DESIGN.md before component code**

Invoke the `omo:frontend` skill and load its design, redesign, perfection, designpowers lane-c, and React tooling references before this task. Treat the approved three-column cockpit and operations-table decisions in the design specification as the concrete reference. Open `DESIGN.md` with a research log naming the rejected control-room/editor/media variants, the selected “A structure × B material” direction, the rejected queue-board/media-gallery home layouts, and the selected operations table. Record these exact contracts:

```css
--ny-canvas: #eee9de;
--ny-surface: #fdfaf3;
--ny-surface-muted: #f3eee4;
--ny-ink: #211f1a;
--ny-ink-muted: #756d60;
--ny-border: #c9c0b0;
--ny-accent: #a43c2e;
--ny-success: #3e6755;
--ny-warning: #a77322;
--ny-danger: #8f2f2f;
--ny-focus: #315f8a;
--ny-radius-1: 2px;
--ny-radius-2: 4px;
--ny-motion-fast: 140ms;
--ny-motion-base: 200ms;
```

Include typography stacks, 4 px spacing scale, 44 px minimum interactive target, icon rules, motion purpose, 1280/1440/1920 layouts, accessibility constraints, and accepted debt limited to OS-dependent CJK glyph rendering.

- [ ] **Step 2: Install primitive dependencies**

```bash
pnpm --dir web add @radix-ui/react-dialog@^1.1.0 @radix-ui/react-dropdown-menu@^2.1.0 @radix-ui/react-tooltip@^1.1.0 @radix-ui/react-toast@^1.2.0 lucide-react@^0.468.0
pnpm --dir web add -D react-grab react-scan
```

Gate both React inspection tools behind `import.meta.env.DEV` and dynamic imports so they are absent from the production bundle. Run `pnpm dlx react-doctor@latest web` before and after primitive implementation and resolve every reported error.

- [ ] **Step 3: Write failing showcase test**

Assert headings and interactive examples exist for buttons, inputs, status stamps, progress rail, table row states, drawer, dialog, menu, tooltip, toast, loading, empty, disconnected, and failure states.

- [ ] **Step 4: Build token sheets and showcase**

Use only semantic tokens from `tokens.css`. The showcase must render default, hover-capable, focus-visible, disabled, destructive, selected, running, success, warning, and failed states without page-specific CSS.

- [ ] **Step 5: Verify primitive gate**

```bash
pnpm --dir web test --run src/workstation/routes/__tests__/PrimitiveShowcasePage.test.tsx
pnpm --dir web build
```

Expected: tests and build pass.

- [ ] **Step 6: Commit**

```bash
git add DESIGN.md web/package.json web/pnpm-lock.yaml web/src/workstation/design web/src/workstation/routes/PrimitiveShowcasePage.tsx web/src/workstation/routes/__tests__/PrimitiveShowcasePage.test.tsx
git commit -m "feat(web): establish workstation design system"
```

### Task 9: Workstation shell, routing, and live invalidation

**Files:**
- Create: `web/src/workstation/WorkstationApp.tsx`
- Create: `web/src/workstation/routes/WorkstationRouter.tsx`
- Create: `web/src/workstation/components/AppShell.tsx`
- Create: `web/src/workstation/components/Sidebar.tsx`
- Create: `web/src/workstation/components/ContextInspector.tsx`
- Create: `web/src/workstation/components/ConnectionBanner.tsx`
- Create: `web/src/workstation/api/events.ts`
- Create: `web/src/workstation/api/useWorkstationEvents.ts`
- Create: `web/src/workstation/testing/fixtures.ts`
- Create: `web/src/workstation/testing/renderWorkstation.tsx`
- Modify: `web/src/router.tsx`
- Create: `web/src/workstation/__tests__/WorkstationApp.test.tsx`

**Interfaces:**
- Produces `/workstation`, `/workstation/queue`, `/workstation/tasks/:taskId`, and development-only `/workstation/design-system`
- Produces: `useWorkstationEvents(): { state: "connecting" | "open" | "fallback"; lastEventId: string | null }`

- [ ] **Step 1: Write failing shell and event tests**

Assert only implemented navigation items appear. Simulate `task.updated` and `queue.updated` events and assert the correct TanStack Query keys are invalidated. Simulate repeated EventSource errors and assert fallback polling becomes active without clearing cached task data.

- [ ] **Step 2: Verify tests fail**

```bash
pnpm --dir web test --run src/workstation/__tests__/WorkstationApp.test.tsx
```

Expected: missing workstation app.

- [ ] **Step 3: Implement shell and routes**

The shell grid is `224px minmax(720px, 1fr) 320px` at 1280 px and `240px minmax(800px, 1fr) 360px` at 1440 px and above. The main column owns scrolling; sidebar and inspector remain sticky within the viewport.

- [ ] **Step 4: Implement SSE invalidation with polling fallback**

Reconnect delays are 1, 2, 5, 10, and 30 seconds. After five consecutive failures, set `fallback` and invalidate active task/queue queries every 15 seconds. A successful SSE open stops the fallback timer.

- [ ] **Step 5: Run shell tests and build**

```bash
pnpm --dir web test --run src/workstation/__tests__/WorkstationApp.test.tsx
pnpm --dir web build
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/workstation web/src/router.tsx
git commit -m "feat(web): add workstation application shell"
```

### Task 10: Task-library page and contextual inspector

**Files:**
- Modify: `web/package.json`
- Modify: `web/pnpm-lock.yaml`
- Create: `web/src/workstation/features/task-library/api.ts`
- Create: `web/src/workstation/features/task-library/filters.ts`
- Create: `web/src/workstation/features/task-library/TaskLibraryPage.tsx`
- Create: `web/src/workstation/features/task-library/TaskTable.tsx`
- Create: `web/src/workstation/features/task-library/TaskInspector.tsx`
- Create: `web/src/workstation/features/task-library/__tests__/TaskLibraryPage.test.tsx`
- Modify: `web/src/workstation/routes/WorkstationRouter.tsx`

**Interfaces:**
- Produces: URL-backed `TaskLibraryFilters`
- Produces: `TaskLibraryPage`, `TaskTable`, and `TaskInspector`

- [ ] **Step 1: Install TanStack Table and write failing page tests**

```bash
pnpm --dir web add @tanstack/react-table@^8.20.0
```

Test initial summary/list queries, debounced search, URL persistence, server-side pagination, stable selection, bulk archive partial failure, empty results, load failure, and a 120-character title.

- [ ] **Step 2: Define URL-backed filter parsing**

```typescript
export interface TaskLibraryFilters {
  query: string;
  statuses: string[];
  sourceKind: "all" | "bilibili" | "local";
  tag: string | null;
  sort: "updated_at" | "created_at" | "title" | "storage_bytes";
  direction: "asc" | "desc";
  page: number;
  pageSize: 25 | 50 | 100;
}
```

Invalid URL values fall back to `updated_at`, `desc`, page 1, and page size 50.

- [ ] **Step 3: Implement page queries and table**

Search debounces for 250 ms. Table sorting and pagination are manual/server-side. Row click selects and updates the inspector; double click or Enter navigates to the task overview. Bulk responses keep failed rows selected and announce the per-row result.

- [ ] **Step 4: Run focused tests**

```bash
pnpm --dir web test --run src/workstation/features/task-library/__tests__/TaskLibraryPage.test.tsx
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/package.json web/pnpm-lock.yaml web/src/workstation/features/task-library web/src/workstation/routes/WorkstationRouter.tsx
git commit -m "feat(web): build scalable task library"
```

### Task 11: Drag-ordered queue page with conflict rollback

**Files:**
- Modify: `web/package.json`
- Modify: `web/pnpm-lock.yaml`
- Create: `web/src/workstation/features/queue/api.ts`
- Create: `web/src/workstation/features/queue/QueuePage.tsx`
- Create: `web/src/workstation/features/queue/QueueList.tsx`
- Create: `web/src/workstation/features/queue/QueueInspector.tsx`
- Create: `web/src/workstation/features/queue/__tests__/QueuePage.test.tsx`
- Modify: `web/src/workstation/routes/WorkstationRouter.tsx`

**Interfaces:**
- Produces: keyboard- and pointer-sortable queue
- Consumes: `QueueSnapshot.revision` and HTTP 409 authoritative snapshots

- [ ] **Step 1: Install dnd-kit and write failing queue tests**

```bash
pnpm --dir web add @dnd-kit/core@^6.1.0 @dnd-kit/sortable@^9.0.0 @dnd-kit/utilities@^3.2.0
```

Test pointer reorder, keyboard reorder, pause/resume, promote-next, active-item immovability, optimistic display, successful revision update, and 409 rollback.

- [ ] **Step 2: Verify tests fail**

```bash
pnpm --dir web test --run src/workstation/features/queue/__tests__/QueuePage.test.tsx
```

Expected: missing queue feature.

- [ ] **Step 3: Implement optimistic reorder**

On drag end, reorder cached queued items immediately and call `PUT /api/v2/queue/order` with the previous revision. On 409, replace cache with the response snapshot and show “队列已在其他操作中变化，已恢复最新顺序。” Do not clear the selected item.

- [ ] **Step 4: Implement accessible controls**

Every row has explicit “上移”, “下移”, “移到队首”, “暂停”, and “恢复” menu actions so all queue operations work without drag-and-drop.

- [ ] **Step 5: Run tests and commit**

```bash
pnpm --dir web test --run src/workstation/features/queue/__tests__/QueuePage.test.tsx
git add web/package.json web/pnpm-lock.yaml web/src/workstation/features/queue web/src/workstation/routes/WorkstationRouter.tsx
git commit -m "feat(web): add manual queue controls"
```

### Task 12: Bilibili and local-file creation drawer

**Files:**
- Create: `web/src/workstation/features/task-create/api.ts`
- Create: `web/src/workstation/features/task-create/NewTaskDrawer.tsx`
- Create: `web/src/workstation/features/task-create/BilibiliSourceStep.tsx`
- Create: `web/src/workstation/features/task-create/LocalSourceStep.tsx`
- Create: `web/src/workstation/features/task-create/TaskOptionsStep.tsx`
- Create: `web/src/workstation/features/task-create/__tests__/NewTaskDrawer.test.tsx`
- Modify: `web/src/workstation/components/AppShell.tsx`

**Interfaces:**
- Produces global `NewTaskDrawer`
- Consumes v2 source inspection, local listing, processing profile, and create endpoints

- [ ] **Step 1: Write failing drawer tests**

Test source-kind selection, URL validation, Bilibili metadata preview, safe local-directory navigation, reference/copy selection, profile/priority selection, API field errors, preserved form values after failure, successful cache invalidation, and navigation to the created task.

- [ ] **Step 2: Verify tests fail**

```bash
pnpm --dir web test --run src/workstation/features/task-create/__tests__/NewTaskDrawer.test.tsx
```

Expected: missing drawer.

- [ ] **Step 3: Implement explicit reducer state**

```typescript
type CreateTaskState =
  | { step: "source"; sourceKind: "bilibili" | "local" | null }
  | { step: "inspect"; source: DraftSource; inspection: SourceInspection | null }
  | { step: "options"; source: ValidatedSource; profileId: string; priority: number }
  | { step: "submitting"; request: CreateTaskRequest };
```

Closing a dirty drawer asks for confirmation. Server field errors map to `source`, `profile_id`, or `priority`; unknown errors appear once in the drawer footer.

- [ ] **Step 4: Implement creation and cache updates**

On success, close the drawer, invalidate summary/list/queue keys, and navigate to `/workstation/tasks/{task_id}`. Do not show stage toggles because `standard` is the only phase-one profile.

- [ ] **Step 5: Run tests and commit**

```bash
pnpm --dir web test --run src/workstation/features/task-create/__tests__/NewTaskDrawer.test.tsx
git add web/src/workstation/features/task-create web/src/workstation/components/AppShell.tsx
git commit -m "feat(web): add inspected task creation"
```

### Task 13: Task overview and feature-parity workspace adapters

**Files:**
- Create: `web/src/workstation/features/task-overview/api.ts`
- Create: `web/src/workstation/features/task-overview/TaskOverviewPage.tsx`
- Create: `web/src/workstation/features/task-overview/StageRail.tsx`
- Create: `web/src/workstation/features/task-overview/RecoveryPanel.tsx`
- Create: `web/src/workstation/features/task-overview/ArtifactList.tsx`
- Create: `web/src/workstation/features/task-overview/ExistingReviewWorkspace.tsx`
- Create: `web/src/workstation/features/task-overview/__tests__/TaskOverviewPage.test.tsx`
- Modify: `web/src/workstation/routes/WorkstationRouter.tsx`
- Modify: `web/src/pages/WorkspacePage.tsx`

**Interfaces:**
- Produces workstation task overview with current subtitle/highlight/export behavior
- Consumes generated v2 overview and existing artifact-content/clip-export endpoints during compatibility

- [ ] **Step 1: Write failing parity tests**

Cover pending, running ASR phase progress, success, cancelled, missing artifact, retryable failure, missing-model recovery, safe log disclosure, subtitle rows, zero highlights, edited export range, failed export preserving input, and successful clip download.

- [ ] **Step 2: Verify tests fail**

```bash
pnpm --dir web test --run src/workstation/features/task-overview/__tests__/TaskOverviewPage.test.tsx
```

Expected: missing overview.

- [ ] **Step 3: Split reusable review behavior from legacy page layout**

Move pure artifact selection, readiness classification, subtitle-row construction, candidate range validation, and export mutation behavior into `ExistingReviewWorkspace.tsx` props/hooks. Keep the current `WorkspacePage` rendering functional by consuming the same extracted logic.

- [ ] **Step 4: Implement overview composition**

The main column shows title/source, seven-stage rail, current-stage progress, recovery panel, and the existing review workspace. The inspector shows safe logs and artifacts for the selected stage. Raw host paths remain behind a technical disclosure.

- [ ] **Step 5: Run parity and existing page tests**

```bash
pnpm --dir web test --run src/workstation/features/task-overview/__tests__/TaskOverviewPage.test.tsx src/pages/__tests__/TaskDetailPage.test.tsx src/pages/__tests__/WorkspacePage.test.tsx
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/workstation/features/task-overview web/src/workstation/routes/WorkstationRouter.tsx web/src/pages/WorkspacePage.tsx
git commit -m "feat(web): add workstation task overview"
```

### Task 14: Release gates, visual QA, documentation, and default cutover

**Files:**
- Create: `web/e2e/workstation-library.spec.ts`
- Create: `web/e2e/workstation-queue.spec.ts`
- Create: `web/e2e/workstation-create.spec.ts`
- Create: `web/e2e/workstation-overview.spec.ts`
- Modify: `web/src/router.tsx`
- Modify: `docs/user-manual.md`
- Modify: `docs/user-manual.zh-CN.md`
- Modify: `docs/processing-flow.md`
- Modify: `docs/processing-flow.zh-CN.md`
- Modify: `docs/wireframes.md`
- Modify: `docs/wireframes.zh-CN.md`
- Modify: `docs/deployment-guide.md`
- Modify: `docs/deployment-guide.zh-CN.md`
- Modify: `.gitignore`

**Interfaces:**
- Makes the workstation route tree the default application entry
- Preserves redirect compatibility from current `/tasks/:taskId`

- [ ] **Step 1: Add deterministic end-to-end journeys**

Use Playwright route fixtures, not a live GPU/backend, to cover:

```typescript
test("creates a Bilibili task and places it in the ordered queue", async ({ page }) => {});
test("creates a referenced local-file task from a trusted root", async ({ page }) => {});
test("searches and paginates a thousand-task library", async ({ page }) => {});
test("rolls back a conflicting queue reorder", async ({ page }) => {});
test("recovers a failed stage and exports a confirmed clip", async ({ page }) => {});
```

Each test asserts user-visible behavior and request payloads. No CSS-class selectors.

- [ ] **Step 2: Run full automated verification**

```bash
cd backend
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tests -q
cd ..
pnpm --dir web api:generate
git diff --exit-code -- web/openapi.json web/src/generated/api-schema.ts
pnpm --dir web test --run
pnpm --dir web build
pnpm --dir web test:e2e
./scripts/export_backend_requirements.sh --check
```

Expected: every command passes. If the environment lacks browser binaries, install the pinned Playwright Chromium build and rerun; do not skip E2E.

- [ ] **Step 3: Run real-browser visual and accessibility QA**

Invoke the `omo:visual-qa` skill and inspect `/workstation`, `/workstation/queue`, and representative task overviews at 1280×800, 1440×900, and 1920×1080. Capture fresh evidence for:

- Empty, populated, 1,000-task, long-title, loading, disconnected, failed, and recovery states.
- Keyboard-only navigation and queue reorder.
- Drawer focus trap and return focus.
- Reduced-motion rendering.
- No unintended horizontal page overflow.
- No token violations, placeholder controls, emoji icons, or unreadable status combinations.

Fix every severity-1/2 visual or accessibility finding and rerun the affected automated tests.

- [ ] **Step 4: Update paired documentation**

Document the task library, queue, local import roots, new-task drawer, task overview, SSE fallback, and trusted-LAN boundary in both English and Chinese. Replace old wireframes with the approved three-column cockpit and operations-table architecture.

Add `/.superpowers/` to `.gitignore` so brainstorming sessions remain local.

- [ ] **Step 5: Switch default routes**

Make `/` render the workstation task library. Redirect current `/tasks/:taskId` to `/workstation/tasks/:taskId`. Keep `/workstation/design-system` available only when `import.meta.env.DEV` is true.

- [ ] **Step 6: Re-run release verification**

```bash
pnpm --dir web test --run
pnpm --dir web build
pnpm --dir web test:e2e
cd backend && PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tests -q
```

Expected: all pass after cutover.

- [ ] **Step 7: Commit**

```bash
git add web/e2e web/src/router.tsx docs/user-manual*.md docs/processing-flow*.md docs/wireframes*.md docs/deployment-guide*.md .gitignore
git commit -m "feat(web): make workstation ui the default"
```

---

## Final plan verification matrix

| Design requirement | Implementing tasks |
| --- | --- |
| Formal migrations and current-data preservation | 1 |
| Large task library, search, tags, pagination, bulk actions | 2, 3, 10 |
| Manually ordered single-GPU queue | 4, 11 |
| Bilibili and trusted local sources | 5, 12 |
| REST snapshots and resumable SSE | 6, 9 |
| Generated OpenAPI frontend contract | 7 |
| Approved visual system and reusable primitives | 8 |
| Three-column desktop cockpit | 9 |
| Task overview, failures, logs, artifacts | 13 |
| Existing subtitle/highlight/export parity | 13 |
| Isolated rollout and atomic default cutover | 9, 14 |
| Backend, frontend, E2E, accessibility, visual gates | 1–14, especially 14 |

## Execution precondition

The current worktree contains pre-existing user changes outside this plan. Before implementation, create an isolated worktree from the commit that the user identifies as the integrated baseline. Do not copy, stash, reset, or commit those unrelated changes as part of this redesign.
