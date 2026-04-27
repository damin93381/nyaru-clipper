# Chinese-only Web UI Copy Plan

## TL;DR
> **Summary**: Convert the current web UI from English-first copy to Chinese-first copy without adding a language switcher, locale routing, or persistence. Centralize frontend-owned UI strings into lightweight copy modules and explicit label maps so the UI becomes easier to maintain and later extend.
> **Deliverables**:
> - Lightweight centralized Chinese copy modules under `web/src/lib/copy/`
> - Chinese UI copy across the current visible web app shell, intake form, detail view, workspace, downloads, and environment status card
> - Explicit Chinese label maps for frontend-owned status/stage/reason labels
> - Updated Vitest and Playwright coverage that asserts Chinese frontend-owned copy while allowing raw backend/artifact free-text to remain unchanged
> **Effort**: Medium
> **Parallel**: YES - 2 waves
> **Critical Path**: Task 1 → Tasks 2/3/4 → Tasks 5/6

## Context
### Original Request
- 给当前项目的 Web UI 添加中文。
- 后续确认：不做语言切换，直接把当前 UI 全部改成中文。

### Interview Summary
- 不做语言切换器。
- 不做 locale 路由。
- 不做语言持久化。
- 首次版本覆盖当前 web app 中所有可见 UI 文案，而不是只做主流程页面。
- 采用 **轻量集中管理文案**，不引入完整 i18n 运行时。
- 测试策略为 **tests-after**。
- 范围边界已锁定：**仅翻译 frontend-owned UI copy**；原样显示的 backend/runtime/artifact free-text 不在本次翻译范围内。

### Metis Review (gaps addressed)
- Guardrail added: the plan must distinguish **frontend-owned UI text** from **raw backend/artifact free-text** so “Chinese-only” is testable and does not accidentally promise backend localization.
- Guardrail added: keep this as a copy refactor only — no provider, no locale state, no route changes, no backend changes.
- Guardrail added: repeated domain terms need a fixed glossary to prevent inconsistent translations across shell, detail, workspace, and tests.
- Guardrail added: known frontend label maps may be translated (for example stage labels, task status labels, known reason codes), but unknown backend free-text must remain unchanged.

## Work Objectives
### Core Objective
Make the current web UI read as Chinese for all frontend-owned visible copy while preserving existing routes, API contracts, runtime behavior, and polling semantics.

### Deliverables
- Shared Chinese copy modules under `web/src/lib/copy/`
- One approved glossary for repeated product/domain terminology
- Chinese replacements in:
  - `web/src/components/AppShell.tsx`
  - `web/src/pages/NewTaskPage.tsx`
  - `web/src/pages/TaskDetailPage.tsx`
  - `web/src/pages/WorkspacePage.tsx`
  - `web/src/components/EnvironmentStatusCard.tsx`
  - `web/src/lib/types.ts` display-label helpers
- Updated Vitest and Playwright assertions for the Chinese UI contract

### Definition of Done (verifiable conditions with commands)
- `pnpm --dir web build` exits `0`.
- `pnpm --dir web test --run src/components/__tests__/EnvironmentStatusCard.test.tsx src/pages/__tests__/NewTaskPage.test.tsx src/pages/__tests__/TaskDetailPage.test.tsx src/pages/__tests__/WorkspacePage.test.tsx src/test/smoke.test.tsx` exits `0`.
- `pnpm --dir web test:e2e -- e2e/task-submit.spec.ts e2e/task-detail.spec.ts e2e/task-flow.spec.ts e2e/workspace.spec.ts` exits `0`.
- The rendered shell header is Chinese and no longer shows `Bilibili VTuber Suite` or `New task` in frontend-owned chrome.
- The submit flow still navigates to `/tasks/<id>`.
- Routes remain `/` and `/tasks/:taskId`.
- Polling cadence remains 3s for non-terminal task states and 15s for terminal task states.
- Raw backend/artifact free-text (for example runtime issue messages or backend-provided `no_candidates` text) is still displayed unchanged unless the frontend owns an explicit label map.

### Must Have
- Keep implementation lightweight: centralized copy constants/modules only.
- Translate current frontend-owned visible UI copy, including labels, buttons, headings, placeholders, loading states, empty states, reserved-panel text, and known display maps.
- Use a glossary for repeated terms and test against exact approved Chinese strings.
- Keep `data-testid` values unchanged.
- Keep route structure, navigation behavior, and API request/response contracts unchanged.

### Must NOT Have
- Must NOT add a language switcher.
- Must NOT add locale provider/context, localStorage persistence, or locale routing.
- Must NOT add i18n dependencies to `web/package.json`.
- Must NOT change backend APIs, runtime payload content, or artifact JSON payloads.
- Must NOT translate raw backend/artifact free-text opportunistically.
- Must NOT change polling intervals, mutation semantics, or submission behavior.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: tests-after using existing Vitest, Playwright, and `pnpm --dir web build`
- QA policy: Every task includes concrete happy-path and failure/edge scenarios
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.{ext}`

## Execution Strategy
### Approved Glossary
The plan must use these exact Chinese terms everywhere unless a file already displays raw backend/artifact text:

- Task → `任务`
- New task → `新建任务`
- Workspace → `工作区`
- Stage → `阶段`
- Stage timeline → `阶段时间线`
- Artifact / Artifacts → `产物`
- Environment status → `环境状态`
- Highlight candidate(s) → `高光候选`
- Downloads → `下载`
- Exported clips → `已导出片段`
- Healthy / Warning / Error → `正常` / `警告` / `错误`
- Satisfied / Needs attention / Unavailable → `已满足` / `需要关注` / `不可用`
- Status map:
  - `pending` → `待处理`
  - `running` → `运行中`
  - `success` → `成功`
  - `failed` → `失败`
  - `skipped` → `已跳过`
- Stage map:
  - `ingest` → `采集`
  - `media_prep` → `媒体准备`
  - `asr` → `语音转写`
  - `translation` → `翻译`
  - `highlight` → `高光`
  - `export` → `导出`
  - `report` → `报告`
- Known reason-code map:
  - `laughter_phrase` → `笑声片段`
  - `emphasis_punctuation` → `强调标点`
- Shared fallback strings:
  - waiting-for-stage fallback → `等待该阶段开始。`
  - no-reason fallback → `暂无原因代码。`
  - no-metadata fallback → `该产物暂无元数据。`

### Parallel Execution Waves
Wave 1: foundation and core UI surfaces
- Task 1: Create centralized Chinese copy modules and shared label maps
- Task 2: Refactor shell and new-task intake copy
- Task 3: Refactor task-detail copy and shared display helpers

Wave 2: workspace/status surfaces and verification
- Task 4: Refactor workspace and environment-status copy
- Task 5: Update Vitest and smoke tests to the Chinese UI contract
- Task 6: Update Playwright e2e assertions without changing route behavior

### Dependency Matrix (full, all tasks)
- Task 1 blocks Tasks 2, 3, 4, 5, and 6
- Task 2 and Task 3 can run in parallel after Task 1
- Task 4 depends on Task 1 and should follow Task 3 because it shares helper-label decisions
- Task 5 depends on Tasks 2, 3, and 4
- Task 6 depends on Tasks 2, 3, and 4

### Agent Dispatch Summary (wave → task count → categories)
- Wave 1 → 3 tasks → `visual-engineering`, `unspecified-high`
- Wave 2 → 3 tasks → `visual-engineering`, `unspecified-high`

## TODOs
> Implementation + Test = ONE task. Never separate.
> EVERY task MUST have: Agent Profile + Parallelization + QA Scenarios.

- [x] 1. Create centralized Chinese copy modules and shared label maps

  **What to do**: Introduce a lightweight copy layer under `web/src/lib/copy/` so frontend-owned Chinese strings stop living inline inside page/component files. Put shared repeated terms and label maps in a single glossary module, then split surface-specific copy into focused modules for shell, intake, task detail, workspace, and environment status. Keep this as plain exported constants/functions — no provider, no hook, no runtime locale state.
  **Must NOT do**: Do not add `react-intl`, `i18next`, or any similar dependency. Do not add `App.tsx` provider wiring. Do not add language keys or English fallback catalogs.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: frontend text architecture and UI-facing label ownership
  - Skills: [`senior-frontend`] - why needed: React/Vite code organization and shared UI copy/module boundaries
  - Omitted: [`senior-backend`] - why not needed: backend contracts stay unchanged

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: [2, 3, 4, 5, 6] | Blocked By: []

  **References**:
  - Pattern: `web/src/App.tsx:1-23` - confirms no locale/provider layer exists and should remain untouched
  - Pattern: `web/src/router.tsx:1-18` - current route structure must remain unchanged
  - Pattern: `web/src/components/AppShell.tsx:18-63` - shell text concentration to extract
  - Pattern: `web/src/pages/NewTaskPage.tsx:14-33` - existing inline option label/help structure
  - Pattern: `web/src/pages/TaskDetailPage.tsx:27-103` - helper and fallback text structure
  - Pattern: `web/src/pages/WorkspacePage.tsx:117-134` - current download-label switch function
  - Pattern: `web/src/components/EnvironmentStatusCard.tsx:15-89` - current inline status-label/message helper structure
  - Pattern: `web/src/lib/types.ts:168-183` - existing stage-label and summary-humanizing helpers to replace or augment with explicit Chinese maps

  **Acceptance Criteria**:
  - [ ] A new copy module directory exists at `web/src/lib/copy/`.
  - [ ] Shared glossary/label-map exports exist for task status, stage labels, and known reason codes.
  - [ ] Surface-specific Chinese copy modules exist for shell, new task, task detail, workspace, and environment status.
  - [ ] `web/package.json` remains dependency-identical; no i18n package is added.
  - [ ] `web/src/App.tsx` and `web/src/router.tsx` remain functionally unchanged.

  **QA Scenarios**:
  ```
  Scenario: Copy modules compile cleanly without adding runtime i18n machinery
    Tool: Bash
    Steps: Run `pnpm --dir web build` after adding the new `web/src/lib/copy/` modules.
    Expected: Exit code 0; the web build succeeds with the new copy modules present and no provider/route changes required.
    Evidence: .sisyphus/evidence/task-1-copy-build.txt

  Scenario: No i18n runtime or locale state was introduced
    Tool: Bash
    Steps: Run `python3 - <<'PY'
from pathlib import Path
paths = [Path('web/package.json'), Path('web/src/App.tsx'), Path('web/src/router.tsx')]
for path in paths:
    text = path.read_text()
    forbidden = ['i18next', 'react-intl', 'IntlProvider', 'localStorage', '/zh/', '/en/']
    hits = [token for token in forbidden if token in text]
    print(path, hits)
PY`
    Expected: `web/package.json` prints no i18n dependency hits, `web/src/App.tsx` prints no provider/localStorage hits, and `web/src/router.tsx` prints no locale route hits.
    Evidence: .sisyphus/evidence/task-1-no-i18n-runtime.txt
  ```

  **Commit**: YES | Message: `Add centralized Chinese web UI copy modules` | Files: `web/src/lib/copy/glossary.ts`, `web/src/lib/copy/appShell.ts`, `web/src/lib/copy/newTask.ts`, `web/src/lib/copy/taskDetail.ts`, `web/src/lib/copy/workspace.ts`, `web/src/lib/copy/environmentStatus.ts`, `web/src/lib/copy/index.ts`

- [x] 2. Refactor shell and new-task intake copy

  **What to do**: Replace inline shell and intake strings with imports from the new copy modules. Keep route navigation, `data-testid` values, query usage, and submission behavior unchanged. Convert the shell/header, reserved regions, intake hero, form labels, option cards, summary strip, and submit button states to Chinese.
  **Must NOT do**: Do not rename `task-url-input` or `task-submit-button`. Do not change the submit mutation payload. Do not change `navigate(`/tasks/${task.task_id}`)`.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: visible shell and form copy replacement in React components
  - Skills: [`senior-frontend`] - why needed: preserve component structure while extracting UI strings
  - Omitted: [`playwright-pro`] - why not needed: this task changes components, not the browser harness itself

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [5, 6] | Blocked By: [1]

  **References**:
  - Pattern: `web/src/components/AppShell.tsx:14-63` - exact shell/header/reserved-panel copy to replace
  - Pattern: `web/src/pages/NewTaskPage.tsx:78-156` - exact intake hero, form, summary strip, and submit-button copy to replace
  - Test: `web/src/test/smoke.test.tsx:77-97` - shell + new-task smoke expectations to update
  - Test: `web/src/pages/__tests__/NewTaskPage.test.tsx:45-84` - input, checkbox, submit, and navigation regression pattern to preserve

  **Acceptance Criteria**:
  - [ ] `AppShell` renders these exact Chinese shell strings:
    - `单机工作站 MVP`
    - `Bilibili VTuber 工作台`
    - `用于提交任务、跟踪处理阶段与后续审核流程的操作界面。`
    - `新建任务`
    - `预留区域`
    - `未来任务列表`
    - `未来工作区`
  - [ ] `NewTaskPage` renders these exact Chinese intake strings:
    - `任务入口`
    - `将 Bilibili 录播加入标准工作流水线`
    - `创建任务`
    - `单任务 MVP`
    - `Bilibili 录播链接`
    - `可见处理选项`
    - `翻译` / `高光` / `导出`
    - `可见阶段`
    - `跳转`
    - `提交成功后会直接跳转到 /tasks/<id>。`
    - `正在创建任务...` / `创建任务`
  - [ ] Submission still navigates to `/tasks/<taskId>` on success.

  **QA Scenarios**:
  ```
  Scenario: Shell and intake render Chinese frontend-owned copy
    Tool: Bash
    Steps: Run `pnpm --dir web test --run src/pages/__tests__/NewTaskPage.test.tsx src/test/smoke.test.tsx`.
    Expected: Exit code 0; tests assert Chinese shell headings, nav label, intake labels, toggle labels, and submit button copy while keeping the same test IDs and route navigation behavior.
    Evidence: .sisyphus/evidence/task-2-shell-intake-vitest.txt

  Scenario: Capability-fetch failure still preserves the main task view with Chinese shell chrome
    Tool: Bash
    Steps: Run `pnpm --dir web test --run src/test/smoke.test.tsx`.
    Expected: Exit code 0; the smoke suite confirms the environment card fallback state still appears while the main intake view remains rendered in Chinese.
    Evidence: .sisyphus/evidence/task-2-shell-failure-state.txt
  ```

  **Commit**: YES | Message: `Translate shell and task intake UI to Chinese` | Files: `web/src/components/AppShell.tsx`, `web/src/pages/NewTaskPage.tsx`, `web/src/lib/copy/appShell.ts`, `web/src/lib/copy/newTask.ts`

- [x] 3. Refactor task-detail copy and shared display helpers

  **What to do**: Move task-detail view copy to Chinese and replace raw frontend-owned status/stage display with explicit Chinese label maps. Update helper functions in `web/src/lib/types.ts` so stage labels and task status displays come from the glossary map. Keep the polling logic and route shape unchanged. For summaries, translate only frontend-owned fallback/known code values; leave unknown backend free-text as-is.
  **Must NOT do**: Do not change `getPollingInterval()`. Do not change route params. Do not rewrite raw backend summary prose into Chinese if it arrives as free-text from the API.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: shared helper semantics plus UI behavior preservation
  - Skills: [`senior-frontend`] - why needed: display-label refactor with route/polling stability
  - Omitted: [`senior-backend`] - why not needed: API payloads remain unchanged

  **Parallelization**: Can Parallel: YES | Wave 1 | Blocks: [5, 6] | Blocked By: [1]

  **References**:
  - Pattern: `web/src/pages/TaskDetailPage.tsx:27-103` - current stage row building, artifact card, and helper usage
  - Pattern: `web/src/pages/TaskDetailPage.tsx:146-246` - current loading, unavailable, failure summary, timeline, artifact empty-state, and polling pill copy
  - Pattern: `web/src/lib/types.ts:168-183` - current `formatStageLabel()` and `humanizeSummary()` behavior
  - Test: `web/src/pages/__tests__/TaskDetailPage.test.tsx:86-118` - existing detail, failure-summary, and polling regression coverage
  - Test: `web/e2e/task-detail.spec.ts:13-76` - browser-level failure-state assertions to update later

  **Acceptance Criteria**:
  - [ ] Loading state uses exact Chinese copy:
    - `正在加载任务`
    - `正在获取任务详情...`
  - [ ] Unavailable/error state uses exact Chinese copy:
    - `任务不可用`
    - `无法加载该任务。`
    - `未知错误`
  - [ ] Detail chrome uses exact Chinese copy:
    - `任务详情`
    - heading form `任务 {taskId}`
    - `可读失败摘要`
    - `{阶段标签}阶段失败`
    - `标准流水线`
    - `阶段时间线`
    - `每 3 秒轮询` / `每 15 秒轮询`
    - `尝试次数：{n}`
    - `暂无阶段日志`
    - `产物`
    - `产物概览`
  - [ ] Known display maps are Chinese:
    - stage labels from glossary map
    - task status badges from glossary map
    - `translation_failed` becomes `翻译失败`
    - unknown free-text summaries remain unchanged
  - [ ] Polling cadence remains 3s for non-terminal states and 15s for terminal states.

  **QA Scenarios**:
  ```
  Scenario: Task detail and failure summary render in Chinese without breaking polling behavior
    Tool: Bash
    Steps: Run `pnpm --dir web test --run src/pages/__tests__/TaskDetailPage.test.tsx`.
    Expected: Exit code 0; the test asserts Chinese headings and failure-summary chrome while `getPollingInterval('pending') === 3000` and `getPollingInterval('failed') === 15000` still hold.
    Evidence: .sisyphus/evidence/task-3-task-detail-vitest.txt

  Scenario: Unknown backend free-text is preserved while frontend fallback copy is Chinese
    Tool: Bash
    Steps: Extend `TaskDetailPage.test.tsx` with a fixture that returns one raw free-text summary such as `Downloaded source video via bbdown`, then run `pnpm --dir web test --run src/pages/__tests__/TaskDetailPage.test.tsx`.
    Expected: Exit code 0; the UI chrome is Chinese, `translation_failed` is rendered as `翻译失败`, and the raw backend free-text summary still appears unchanged.
    Evidence: .sisyphus/evidence/task-3-summary-boundary.txt
  ```

  **Commit**: YES | Message: `Translate task detail UI and shared labels to Chinese` | Files: `web/src/pages/TaskDetailPage.tsx`, `web/src/lib/types.ts`, `web/src/lib/copy/taskDetail.ts`, `web/src/lib/copy/glossary.ts`

- [x] 4. Refactor workspace and environment-status copy

  **What to do**: Convert the workspace and environment-status card to Chinese for all frontend-owned copy. Replace inline workspace headings, control labels, download labels, empty states, and environment-status shell copy with copy-module imports. Add explicit mappings for known reason codes and download labels. Keep raw payload messages such as `no_candidates` text and `capabilities.issues[].message` unchanged.
  **Must NOT do**: Do not translate transcript content (`你好`, `こんにちは`, etc.) or raw backend/runtime issue messages. Do not rename download URLs or artifact kinds.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: component-heavy UI text replacement plus display-map ownership
  - Skills: [`senior-frontend`] - why needed: visible UI state refactor with consistent glossary usage
  - Omitted: [`playwright-pro`] - why not needed: browser harness updates come later in Task 6

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: [5, 6] | Blocked By: [1, 3]

  **References**:
  - Pattern: `web/src/pages/WorkspacePage.tsx:117-134` - download-label switch function to replace with Chinese labels
  - Pattern: `web/src/pages/WorkspacePage.tsx:242-449` - workspace headings, controls, empty states, exported clips, and candidate copy
  - Pattern: `web/src/components/EnvironmentStatusCard.tsx:15-89` - status labels and explanatory copy to replace with Chinese
  - Pattern: `web/src/components/EnvironmentStatusCard.tsx:96-192` - loading/unavailable/healthy/warning/error render paths
  - Test: `web/src/pages/__tests__/WorkspacePage.test.tsx:80-205` - candidate, zero-state, and download assertion pattern
  - Test: `web/src/components/__tests__/EnvironmentStatusCard.test.tsx:112-154` - environment card variant assertions to update
  - Test: `web/e2e/workspace.spec.ts:80-302` - browser-level workspace flow assertions to update later

  **Acceptance Criteria**:
  - [ ] Workspace renders exact Chinese frontend-owned copy including:
    - `工作区`
    - `字幕审阅与高光确认`
    - `任务 10 工作区`
    - `字幕`
    - `中文字幕与双语字幕行`
    - `片段`
    - `中文字幕`
    - `双语字幕`
    - `暂无双语翻译。`
    - `高光候选`
    - `排名候选确认`
    - `开始（秒）`
    - `结束（秒）`
    - `正在导出片段...` / `确认导出`
    - `零候选状态`
    - `暂无可用高光候选`
    - `下载`
    - `产物下载`
    - `已导出片段`
    - `可下载的 MP4 产物`
    - `下载已导出片段`
  - [ ] `getDownloadLabel()` returns Chinese labels for all known downloadable artifact kinds.
  - [ ] Known reason codes render Chinese labels (`笑声片段`, `强调标点`), while unknown codes remain raw.
  - [ ] `EnvironmentStatusCard` renders exact Chinese frontend-owned chrome, including:
    - `环境状态`
    - `正常` / `警告` / `错误`
    - `已满足` / `需要关注` / `不可用`
    - `当前配置`
    - `加速能力`
    - `当前警告`
    - `已检测问题`
  - [ ] Raw `capabilities.issues[].message` text and raw `no_candidates` text remain unchanged.

  **QA Scenarios**:
  ```
  Scenario: Workspace renders Chinese UI chrome while preserving raw backend no-candidate text
    Tool: Bash
    Steps: Run `pnpm --dir web test --run src/pages/__tests__/WorkspacePage.test.tsx`.
    Expected: Exit code 0; tests assert Chinese headings, control labels, and download labels while the mocked backend `no_candidates` free-text remains visible unchanged.
    Evidence: .sisyphus/evidence/task-4-workspace-vitest.txt

  Scenario: Environment card renders Chinese chrome while preserving backend issue message payloads
    Tool: Bash
    Steps: Run `pnpm --dir web test --run src/components/__tests__/EnvironmentStatusCard.test.tsx`.
    Expected: Exit code 0; tests assert Chinese card chrome and status badges while the mocked backend WSL mismatch issue message still appears in its original payload text.
    Evidence: .sisyphus/evidence/task-4-environment-vitest.txt
  ```

  **Commit**: YES | Message: `Translate workspace and environment status UI to Chinese` | Files: `web/src/pages/WorkspacePage.tsx`, `web/src/components/EnvironmentStatusCard.tsx`, `web/src/lib/copy/workspace.ts`, `web/src/lib/copy/environmentStatus.ts`, `web/src/lib/copy/glossary.ts`

- [x] 5. Update Vitest and smoke tests to the Chinese UI contract

  **What to do**: Rewrite frontend unit/component/smoke assertions so they check the approved Chinese literals for frontend-owned UI text. Preserve route assertions, submit behavior, and the backend-free-text boundary in fixtures. Keep `data-testid` usage stable to reduce test brittleness.
  **Must NOT do**: Do not translate or mutate mocked backend payload messages just to make tests pass if those payload strings are intentionally out of scope.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: test contract rewrite across component and smoke layers
  - Skills: [`senior-frontend`, `senior-qa`] - why needed: precise Testing Library assertions and regression-safe fixture updates
  - Omitted: [`playwright-pro`] - why not needed: this task only covers Vitest/smoke

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [F1-F4] | Blocked By: [2, 3, 4]

  **References**:
  - Test: `web/src/test/smoke.test.tsx:77-97` - shell + environment fallback coverage to convert to Chinese assertions
  - Test: `web/src/pages/__tests__/NewTaskPage.test.tsx:45-84` - intake form and navigation regression assertions
  - Test: `web/src/pages/__tests__/TaskDetailPage.test.tsx:86-118` - detail/failure/polling assertions
  - Test: `web/src/pages/__tests__/WorkspacePage.test.tsx:80-205` - workspace happy + zero-candidate assertions
  - Test: `web/src/components/__tests__/EnvironmentStatusCard.test.tsx:112-154` - environment-card variant assertions
  - Pattern: `web/src/test/setup.ts` - shared Vitest setup remains unchanged

  **Acceptance Criteria**:
  - [ ] The exact Vitest command in Definition of Done passes.
  - [ ] Smoke tests assert Chinese shell copy and Chinese task-intake heading.
  - [ ] New-task tests assert Chinese checkbox labels and Chinese submit button text while preserving route navigation to `/tasks/task-created123`.
  - [ ] Task-detail tests assert Chinese headings and Chinese failure-summary chrome while preserving polling assertions.
  - [ ] Workspace tests assert Chinese download labels and Chinese control labels while preserving raw backend `no_candidates` text.
  - [ ] Environment-status tests assert Chinese status labels and Chinese explanatory chrome while preserving raw backend issue messages.

  **QA Scenarios**:
  ```
  Scenario: Vitest contract passes for the full Chinese frontend-owned UI surface
    Tool: Bash
    Steps: Run `pnpm --dir web test --run src/components/__tests__/EnvironmentStatusCard.test.tsx src/pages/__tests__/NewTaskPage.test.tsx src/pages/__tests__/TaskDetailPage.test.tsx src/pages/__tests__/WorkspacePage.test.tsx src/test/smoke.test.tsx`.
    Expected: Exit code 0; all updated tests pass with Chinese frontend-owned copy assertions and unchanged behavioral regressions.
    Evidence: .sisyphus/evidence/task-5-vitest-suite.txt

  Scenario: No stale English assertions remain for frontend-owned copy in updated Vitest files
    Tool: Bash
    Steps: Run `python3 - <<'PY'
from pathlib import Path
targets = [
    Path('web/src/components/__tests__/EnvironmentStatusCard.test.tsx'),
    Path('web/src/pages/__tests__/NewTaskPage.test.tsx'),
    Path('web/src/pages/__tests__/TaskDetailPage.test.tsx'),
    Path('web/src/pages/__tests__/WorkspacePage.test.tsx'),
    Path('web/src/test/smoke.test.tsx'),
]
needles = ['New task', 'Environment status', 'Queue a Bilibili VOD', 'Download bilingual subtitles', 'Download task report']
for path in targets:
    text = path.read_text()
    hits = [needle for needle in needles if needle in text]
    print(path, hits)
PY`
    Expected: The printed hit lists are empty or only contain intentionally preserved backend free-text fixtures, not stale frontend-owned assertion literals.
    Evidence: .sisyphus/evidence/task-5-no-stale-english-assertions.txt
  ```

  **Commit**: YES | Message: `Update frontend tests for Chinese UI copy` | Files: `web/src/test/smoke.test.tsx`, `web/src/pages/__tests__/NewTaskPage.test.tsx`, `web/src/pages/__tests__/TaskDetailPage.test.tsx`, `web/src/pages/__tests__/WorkspacePage.test.tsx`, `web/src/components/__tests__/EnvironmentStatusCard.test.tsx`

- [x] 6. Update Playwright e2e assertions without changing route behavior

  **What to do**: Update browser tests so they assert Chinese frontend-owned UI strings while preserving the same mocked routes, task submission flow, and route targets. Keep backend-provided fixture payload text unchanged where it is intentionally outside the frontend-owned translation boundary.
  **Must NOT do**: Do not alter the Playwright `webServer` configuration. Do not change test routes from `/` and `/tasks/:taskId`. Do not rewrite fixture payload prose merely to claim full Chinese coverage.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: browser-level regression contract rewrite with route and payload-boundary preservation
  - Skills: [`senior-qa`, `playwright-pro`] - why needed: Playwright assertion updates and route-fixture stability
  - Omitted: [`senior-backend`] - why not needed: no backend changes are part of this task

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: [F1-F4] | Blocked By: [2, 3, 4]

  **References**:
  - Test: `web/e2e/task-submit.spec.ts:13-92` - submit flow, redirect, and stage heading assertions
  - Test: `web/e2e/task-detail.spec.ts:13-76` - failed translation detail-state assertions
  - Test: `web/e2e/task-flow.spec.ts:116-294` - end-to-end happy flow with task submit, workspace, and clip export
  - Test: `web/e2e/workspace.spec.ts:80-302` - workspace happy and zero-candidate browser assertions
  - Pattern: `web/playwright.config.ts:4-17` - Playwright server/baseURL contract that must remain unchanged

  **Acceptance Criteria**:
  - [ ] The exact Playwright command in Definition of Done passes.
  - [ ] Browser tests assert Chinese frontend-owned headings/buttons/labels for shell, task intake, detail view, workspace, and download actions.
  - [ ] Browser tests still assert route behavior:
    - form submit ends at `/tasks/<id>`
    - direct task-detail navigation still works
  - [ ] Browser tests explicitly allow raw backend free-text where the mocked payload owns it, such as zero-candidate explanation strings.
  - [ ] No Playwright config changes are required.

  **QA Scenarios**:
  ```
  Scenario: Chinese browser UI contract passes end-to-end
    Tool: Bash
    Steps: Run `pnpm --dir web test:e2e -- e2e/task-submit.spec.ts e2e/task-detail.spec.ts e2e/task-flow.spec.ts e2e/workspace.spec.ts`.
    Expected: Exit code 0; Playwright verifies Chinese frontend-owned UI copy, stable route behavior, and clip-export/download flows.
    Evidence: .sisyphus/evidence/task-6-playwright-suite.txt

  Scenario: Route and payload boundaries remain unchanged under browser tests
    Tool: Bash
    Steps: Re-run `pnpm --dir web test:e2e -- e2e/task-submit.spec.ts e2e/task-detail.spec.ts e2e/task-flow.spec.ts e2e/workspace.spec.ts` after confirming mocked fixture payload prose such as `No highlight candidates cleared the minimum score threshold...` remains in English.
    Expected: Exit code 0; browser tests pass with `/` and `/tasks/:taskId` intact and with out-of-scope backend free-text still visible when intentionally mocked.
    Evidence: .sisyphus/evidence/task-6-route-boundary.txt
  ```

  **Commit**: YES | Message: `Update Playwright coverage for Chinese web UI` | Files: `web/e2e/task-submit.spec.ts`, `web/e2e/task-detail.spec.ts`, `web/e2e/task-flow.spec.ts`, `web/e2e/workspace.spec.ts`

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [x] F1. Plan Compliance Audit — oracle
- [x] F2. Code Quality Review — unspecified-high
- [x] F3. Real Manual QA — unspecified-high (+ playwright if UI)
- [x] F4. Scope Fidelity Check — deep

## Commit Strategy
- Commit 1: `Add centralized Chinese web UI copy modules`
- Commit 2: `Translate shell and task intake UI to Chinese`
- Commit 3: `Translate task detail UI and shared labels to Chinese`
- Commit 4: `Translate workspace and environment status UI to Chinese`
- Commit 5: `Update frontend tests for Chinese UI copy`
- Commit 6: `Update Playwright coverage for Chinese web UI`

## Success Criteria
- All frontend-owned visible UI copy in the current web app is rendered in Chinese.
- Known frontend label maps (statuses, stages, reason codes, download labels, fallback strings) are Chinese and glossary-consistent.
- Routes, submit navigation, polling intervals, and API contracts remain unchanged.
- Raw backend/artifact free-text is not falsely localized and remains visible where intended.
- The full build, Vitest suite, and Playwright suite listed above pass.
