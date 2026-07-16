# Optional Highlight Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each new workstation task opt into automatic highlight filtering, with the UI defaulting to disabled while legacy tasks remain enabled.

**Architecture:** Persist an immutable `Task.highlight_filtering_enabled` boolean through an Alembic migration and the v2 create-task contract. The runner keeps the canonical seven-stage pipeline, returning an explicit skipped directive for `highlight` when the value is false. The workstation projection and review workspace interpret that intentional skip as unavailable rather than as a missing artifact.

**Tech Stack:** FastAPI, Pydantic, SQLModel, Alembic, SQLite, pytest, React 18, TypeScript, TanStack Query, Vitest, generated OpenAPI types.

## Global Constraints

- Keep `CANONICAL_STAGES` unchanged and preserve the single-worker, single-GPU workstation model.
- New v2 tasks default `highlight_filtering_enabled` to `false`; existing rows and legacy v1 creation default to `true`.
- Use an Alembic migration for persisted schema changes; never hand-edit runtime SQLite data.
- Keep the checked-in OpenAPI JSON and generated TypeScript schema synchronized with the FastAPI contract.
- Preserve unrelated dirty worktree changes; do not stage or commit as part of this task.

---

### Task 1: Persist the immutable task option and expose it in v2 creation

**Files:**
- Create: `backend/alembic/versions/20260714_01_optional_highlight_filtering.py`
- Modify: `backend/app/models.py:47-58`
- Modify: `backend/app/api/routes/workstation_tasks.py:60-112,214-248`
- Modify: `backend/app/api/schemas/workstation.py:197-206`
- Modify: `backend/app/repositories/workstation.py:126-157`
- Modify: `backend/tests/workstation/test_domain_migration.py`
- Modify: `backend/tests/workstation/test_task_create_api.py`

**Interfaces:**
- Produces `Task.highlight_filtering_enabled: bool`, with persistence default `True`.
- Produces `CreateWorkstationTaskRequest.highlight_filtering_enabled: bool = False` and the same field on `CreateWorkstationTaskResponse`.
- Produces `TaskOverview.highlight_filtering_enabled: bool` for the review UI.
- Consumes `highlight_filtering_enabled` in `_create_workstation_task(session, payload)`.

- [ ] **Step 1: Write migration and v2 API tests that fail before implementation**

```python
def test_upgrade_database_adds_enabled_highlight_filtering_to_legacy_tasks(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "task-state.sqlite3"
    _create_legacy_database(database_path, "task-legacy-highlight")
    upgrade_database(f"sqlite:///{database_path}")
    with Session(get_engine()) as session:
        task = session.get(Task, "task-legacy-highlight")
    assert task is not None
    assert task.highlight_filtering_enabled is True

def test_v2_task_creation_defaults_highlight_filtering_to_disabled(client: TestClient) -> None:
    response = client.post("/api/v2/tasks", json={
        "source": {"kind": "bilibili", "url": "https://www.bilibili.com/video/BV1highlightoff"},
        "profile_id": "standard", "priority": 0,
    })
    assert response.status_code == 201
    assert response.json()["highlight_filtering_enabled"] is False
    with session_scope() as session:
        assert session.get(Task, response.json()["task_id"]).highlight_filtering_enabled is False
```

- [ ] **Step 2: Run the focused tests and verify the expected red state**

Run: `backend/.venv/bin/pytest backend/tests/workstation/test_domain_migration.py backend/tests/workstation/test_task_create_api.py -q`

Expected: failure because `Task` and the response schema do not yet define `highlight_filtering_enabled`.

- [ ] **Step 3: Add the model field, migration, and request/response mapping**

```python
# backend/app/models.py
highlight_filtering_enabled: bool = Field(default=True)

# backend/app/api/routes/workstation_tasks.py
class CreateWorkstationTaskRequest(WorkstationSchema):
    source: TaskSource
    profile_id: Literal["standard"]
    priority: int = 0
    highlight_filtering_enabled: bool = False

class CreateWorkstationTaskResponse(WorkstationSchema):
    task_id: str
    profile_id: Literal["standard"]
    priority: int
    highlight_filtering_enabled: bool
    status: Literal["pending"]

class TaskOverview(TaskListItem):
    highlight_filtering_enabled: bool
    # existing overview fields remain unchanged

# `_create_workstation_task`
task = Task(..., highlight_filtering_enabled=payload.highlight_filtering_enabled)
```

Create revision `20260714_01` with `down_revision = "20260712_02"`; its upgrade adds non-null `task.highlight_filtering_enabled` with `server_default=sa.true()`, then removes the server default. Its downgrade drops that column.

- [ ] **Step 4: Run the focused tests and verify green**

Run: `backend/.venv/bin/pytest backend/tests/workstation/test_domain_migration.py backend/tests/workstation/test_task_create_api.py -q`

Expected: PASS, including a legacy database upgraded to `True` and a v2 omission persisted as `False`.

### Task 2: Make the pipeline and projection honor deliberate skips

**Files:**
- Modify: `backend/app/services/task_runner.py:306-318`
- Modify: `backend/app/api/schemas/workstation.py:14-19`
- Modify: `backend/app/repositories/workstation.py:460-491`
- Modify: `backend/tests/workstation/test_run_projection.py`
- Modify: `backend/tests/workstation/test_task_library_api.py`

**Interfaces:**
- Produces `_execute_highlight(session, task_id) -> StageDirective | HighlightStageResult`.
- Consumes `Task.highlight_filtering_enabled` and returns `StageDirective(status="skipped", summary="Automatic highlight filtering disabled for this task")` when disabled.
- Produces highlight artifact-readiness record status `not_applicable` for a skipped disabled stage; the public schema accepts that status.

- [ ] **Step 1: Write failing runner and overview tests**

```python
def test_disabled_highlight_filtering_skips_analyzer_and_mirrors_stage_run(database, monkeypatch) -> None:
    _create_task(database, "task-no-highlights", highlight_filtering_enabled=False)
    monkeypatch.setattr(task_runner, "analyze_task_highlights", lambda *_: pytest.fail("must not run"))
    with Session(database) as session:
        result = task_runner.run_task_pipeline(session, "task-no-highlights", start_stage_name="highlight")
        stage = session.exec(select(TaskStage).where(TaskStage.task_id == result.task_id, TaskStage.name == "highlight")).one()
        run_stage = session.exec(select(StageRun).where(StageRun.name == "highlight")).one()
    assert stage.status == run_stage.status == "skipped"
    assert stage.summary == "Automatic highlight filtering disabled for this task"

def test_overview_marks_disabled_highlight_artifact_not_applicable(client: TestClient) -> None:
    overview = client.get("/api/v2/tasks/task-disabled-highlights").json()
    readiness = next(item for item in overview["artifact_readiness"] if item["stage_name"] == "highlight")
    assert readiness["status"] == "not_applicable"
```

- [ ] **Step 2: Run focused tests and verify red**

Run: `backend/.venv/bin/pytest backend/tests/workstation/test_run_projection.py backend/tests/workstation/test_task_library_api.py -q`

Expected: failure because the runner calls the analyzer and the artifact-readiness type has no `not_applicable` state.

- [ ] **Step 3: Add a focused conditional executor and projection state**

```python
def _execute_highlight(session: Session, task_id: str) -> StageDirective | HighlightStageResult:
    task = session.get(Task, task_id)
    if task is None:
        raise ValueError(f"Unknown task_id: {task_id}")
    if not task.highlight_filtering_enabled:
        return StageDirective(status="skipped", summary="Automatic highlight filtering disabled for this task")
    return analyze_task_highlights(session, task_id)

STAGE_EXECUTORS["highlight"] = _execute_highlight
```

Extend the workstation artifact-readiness status literal with `not_applicable`, return it when the highlight stage is skipped, and map it to a neutral UI state rather than `missing`.

- [ ] **Step 4: Run focused tests and verify green**

Run: `backend/.venv/bin/pytest backend/tests/workstation/test_run_projection.py backend/tests/workstation/test_task_library_api.py -q`

Expected: PASS, with the canonical run history retained and no false missing-artifact warning.

### Task 3: Update the generated API contract and task-creation drawer

**Files:**
- Modify: `web/openapi.json`
- Modify: `web/src/generated/api-schema.ts`
- Modify: `web/src/workstation/features/task-create/api.ts:11-35`
- Modify: `web/src/workstation/features/task-create/NewTaskDrawer.tsx`
- Modify: `web/src/workstation/features/task-create/TaskOptionsStep.tsx`
- Modify: `web/src/workstation/features/task-create/__tests__/NewTaskDrawer.test.tsx`

**Interfaces:**
- Consumes generated `CreateWorkstationTaskRequest.highlight_filtering_enabled`.
- Produces `TaskOptionsStep.onHighlightFilteringChange(enabled: boolean)` and a checked/unchecked accessible switch.
- Sends `highlight_filtering_enabled: false` by default from the drawer.

- [ ] **Step 1: Write a failing drawer interaction test**

```tsx
it("submits automatic highlight filtering disabled by default and preserves an enabled choice", async () => {
  renderDrawer();
  // select and inspect a valid source, then reach options
  expect(screen.getByRole("checkbox", { name: "启用自动高光筛选" })).not.toBeChecked();
  fireEvent.click(screen.getByRole("checkbox", { name: "启用自动高光筛选" }));
  fireEvent.click(screen.getByRole("button", { name: "创建任务" }));
  await waitFor(() => expect(requests.at(-1)?.body).toMatchObject({ highlight_filtering_enabled: true }));
});
```

- [ ] **Step 2: Run the drawer test and verify red**

Run: `pnpm --dir web vitest run src/workstation/features/task-create/__tests__/NewTaskDrawer.test.tsx`

Expected: failure because the checkbox and request property do not exist.

- [ ] **Step 3: Regenerate the API schema and add the controlled option**

Run: `pnpm --dir web api:generate`

Then extend the drawer reducer state with `highlightFilteringEnabled: false`, include it in reset and `set-options`, pass it to `TaskOptionsStep`, and include `highlight_filtering_enabled: state.highlightFilteringEnabled` in the creation payload. Render a semantic checkbox labelled `启用自动高光筛选` with helper copy explaining that it creates ranked candidates and is disabled by default.

- [ ] **Step 4: Run contract and drawer tests and verify green**

Run: `pnpm --dir web vitest run src/workstation/features/task-create/__tests__/NewTaskDrawer.test.tsx && pnpm --dir web api:check`

Expected: PASS, with checked-in OpenAPI/schema output matching the backend and the submitted value matching the control.

### Task 4: Explain the disabled state in the review workspace and verify the full change

**Files:**
- Modify: `web/src/lib/taskState.ts`
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/lib/copy/workspace.ts`
- Modify: `web/src/workstation/features/task-overview/ExistingReviewWorkspace.tsx`
- Modify: `web/src/workstation/features/task-overview/__tests__/TaskOverviewPage.test.tsx`
- Modify: `docs/operator-manual.md`
- Modify: `docs/operator-manual.zh-CN.md`

**Interfaces:**
- Consumes `ArtifactReadinessRecord.status === "not_applicable"` for `highlight_candidates_json`.
- Produces a review-workspace message that automatic highlight filtering was disabled, without a retry action or a missing-artifact warning.

- [ ] **Step 1: Write a failing review-workspace test**

```tsx
it("explains that automatic candidate generation was disabled", async () => {
  renderOverview({ artifact_readiness: [{ stage_name: "highlight", kind: "highlight_candidates_json", status: "not_applicable", artifact_id: null, path: null }] });
  expect(await screen.findByText("此任务未启用自动高光筛选，因此不会生成候选片段。"))
    .toBeVisible();
  expect(screen.queryByText(WORKSPACE_COPY.readiness.messages.missing)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the review test and verify red**

Run: `pnpm --dir web vitest run src/workstation/features/task-overview/__tests__/TaskOverviewPage.test.tsx`

Expected: failure because `not_applicable` is not classified or rendered.

- [ ] **Step 3: Add neutral classification, Chinese copy, and operator documentation**

Extend `ArtifactReadinessClassification` and its renderer with `not_applicable`; give only the highlight section the explicit disabled message. Do not add a retry action. Document that automatic highlighter selection is off by default for new workstation tasks, can be enabled before creation, and is immutable afterward; write the same operational guidance in the English and Chinese manuals.

Ensure `firstBlockingReadiness()` ignores `not_applicable`, so a completed task with intentionally skipped candidates is still classified as successful.

- [ ] **Step 4: Run the complete verification set**

Run:
`backend/.venv/bin/pytest backend/tests/workstation/test_domain_migration.py backend/tests/workstation/test_task_create_api.py backend/tests/workstation/test_run_projection.py backend/tests/workstation/test_task_library_api.py backend/tests/test_requirements_export.py -q`

Run:
`pnpm --dir web vitest run src/workstation/features/task-create/__tests__/NewTaskDrawer.test.tsx src/workstation/features/task-overview/__tests__/TaskOverviewPage.test.tsx && pnpm --dir web build && git diff --check`

Expected: all selected tests and build pass; only intended source, generated-contract, test, docs, migration, and plan/spec changes appear in the diff.

- [ ] **Step 5: Perform desktop visual verification**

Start the existing dev stack if needed, open the new-task drawer at `http://localhost:5173`, verify the unchecked control, toggle it, create a disabled task, and verify its overview displays the skipped highlight stage and neutral candidate message. Capture the observed result in the task handoff.
