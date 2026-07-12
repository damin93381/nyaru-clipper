# Nyaru-Clipper Long-Term Workstation Redesign

**Date:** 2026-07-12
**Status:** Approved for implementation planning
**Scope:** Long-term single-user workstation architecture, with detailed specification for the first delivery phase

## 1. Purpose

Nyaru-Clipper will be redesigned as a durable desktop-first media processing workstation rather than an MVP task submission page. The redesign may change both frontend and backend architecture. It must preserve the trusted-LAN, single-user, single-GPU operating model while making large task libraries, queue control, processing recovery, subtitle review, highlight selection, and exports feel like one coherent product.

The existing visual system, placeholder rails, reserved controls, and page-level CSS are not retained as a design constraint. Existing pipeline behavior and user data remain migration constraints.

## 2. Product constraints

- One operator on a trusted local network.
- One GPU-bound pipeline task may run at a time.
- Desktop displays only; supported viewport width starts at 1280 px.
- The task library may contain hundreds to thousands of tasks.
- Sources in the first long-term architecture are Bilibili VOD URLs and local video files.
- The primary runtime remains host-based uv + pnpm. Docker remains a fallback.
- The application must continue to operate without public-cloud accounts or external UI dependencies.
- Existing SQLite tasks and artifacts must survive migration.

## 3. Delivery decomposition

The redesign is split into four independently deliverable subprojects:

1. **Product foundation:** design system, application shell, task library, queue, task creation, and task overview.
2. **Processing control:** real-time progress, logs, cancellation and recovery, runtime diagnostics, and model management.
3. **Content workstation:** video preview, waveform, bilingual subtitle editing, and highlight candidate adjustment.
4. **Output management:** export presets, export jobs, finished-media library, reports, and storage cleanup.

The implementation order is fixed to this sequence. This document defines the whole-product direction and the detailed contract for subproject 1.

## 4. Product architecture

### 4.1 Desktop shell

The application uses a persistent three-column cockpit:

- **Left navigation:** stable product modules and global navigation.
- **Main workspace:** the current page's primary task.
- **Context inspector:** details and actions for the selected task, queue entry, artifact, or active GPU job.

The inspector is not a decorative rail. Its content follows selection and prevents unnecessary navigation for quick status checks and actions.

### 4.2 Primary navigation

The long-term navigation model is:

- Task library
- Processing queue
- Finished exports
- Storage management
- Runtime environment
- Settings

Task-specific sections are entered through a selected task and later grow to:

- Overview
- Transcript
- Highlights
- Exports
- Technical activity

Navigation items are shown only when the destination is implemented. The product must not ship placeholder panels or non-functional controls.

### 4.3 Home page

The task library is the default page. It uses an operations table rather than a cover grid or a Kanban board.

The page includes:

- Summary counts for active, queued, review-required, failed, and archived tasks.
- Storage usage summary.
- Full-text search.
- Filters for status, source, tags, dates, and readiness.
- Stable sorting and server-side pagination.
- Dense rows with title, source, tags, current stage, progress, updated time, storage size, and quick actions.
- Multi-selection for tagging, archiving, deletion, and requeueing.
- A context inspector that shows the selected task without forcing navigation.
- A persistent active-GPU-job summary in the inspector when nothing else is selected.

### 4.4 Queue page

The queue is a dedicated ordered list optimized for manual control:

- Drag-and-drop ordering.
- Explicit priority.
- Pause and resume.
- Cancel pending work.
- Promote an item to the next position.
- Estimated start ordering when estimates are available.
- Clear separation of active, queued, paused, and intervention-required tasks.

The interface updates queue order optimistically. The backend remains authoritative and returns a queue revision used to detect conflicting edits; rejected mutations always roll back to the returned snapshot.

### 4.5 Task creation

“New task” is the global primary action and opens a right-side drawer without leaving the current context.

The flow is:

1. Select Bilibili URL or local file.
2. Validate and preview source metadata.
3. Select a named processing profile and queue priority.
4. Confirm creation.

For local files, the backend exposes only configured, trusted import roots. The operator chooses a server-visible path and selects either:

- Reference the original file.
- Copy the file into managed task storage.

Arbitrary filesystem traversal is prohibited. Large video files are not implicitly uploaded through the browser.

## 5. Visual design system

### 5.1 Direction

The chosen direction combines:

- The structure and state clarity of a professional operations console.
- The warmth, typography, and material quality of a Japanese editorial studio.

The product should feel precise and calm, not cyberpunk, generic SaaS, or decorative vintage.

### 5.2 Visual tokens

The design system will define semantic tokens before product components are implemented. The intended palette families are:

- Warm grey paper canvas.
- Soft ivory elevated surfaces.
- Deep ink primary text.
- Grey-brown secondary text.
- Vermilion primary action and active-state accent.
- Pine green success.
- Ochre warning.
- Dark red destructive and failure states.
- Fine warm-grey borders.

Pure black, pure white, neon accents, and broad decorative gradients are avoided.

Surface treatment uses fine rules, restrained paper-grid texture, small radii, and subtle offset shadows. Glassmorphism is not part of the product language.

### 5.3 Typography

- Page titles and media-project names use the system CJK serif stack: `"Noto Serif CJK SC"`, `"Source Han Serif SC"`, `"Songti SC"`, `STSong`, then `serif`.
- Tables, controls, and long Chinese text use a self-hosted Inter Latin variable font followed by `"Noto Sans CJK SC"`, `"Microsoft YaHei UI"`, `"PingFang SC"`, then `sans-serif`.
- Timecodes, task identifiers, model names, and technical logs use `"Cascadia Code"`, `"JetBrains Mono"`, `"SFMono-Regular"`, then `monospace`.
- The UI does not download fonts at runtime or depend on a font CDN.

### 5.4 Component primitives

The first reusable component layer includes:

- App shell, sidebar, top command bar, and context inspector.
- Data table, pagination, filters, and bulk-action bar.
- Status stamp, source badge, priority control, and seven-stage progress rail.
- Drawer, dialog, popover, menu, tooltip, and notification center.
- Form fields, source picker, processing-profile selector, and validation messages.
- Loading skeleton, empty state, unavailable state, failure panel, and recovery action group.
- Log summary and technical disclosure.

Icons use a consistent SVG icon set. Emoji are not used as interface icons.

### 5.5 Motion and accessibility

Motion is limited to meaningful state transitions such as drawer entry, row selection, inspector replacement, and progress changes. Animations use transform and opacity, normally within 140–220 ms, and respect reduced-motion preferences.

All controls have visible keyboard focus, accessible names, adequate contrast, and non-color status indicators. High information density must not reduce hit targets or text legibility.

## 6. Backend domain model

The current Task/TaskJob/TaskStage split is evolved into clearer responsibilities:

- **MediaSource:** Bilibili or local-file source identity and source metadata.
- **Task:** user-facing media project, title, cover, tags, archival state, and storage summary.
- **QueueEntry:** manual position, priority, paused state, and queue revision.
- **PipelineRun:** one processing attempt for a task.
- **StageRun:** status, timing, progress, failure code, and recovery metadata for one stage attempt.
- **Artifact:** managed output with kind, readiness, integrity, size, and provenance.

Later subprojects add export jobs, transcript revisions, and highlight revisions without overloading Task or StageRun.

Schema evolution uses a formal migration tool. Migrations are idempotent, tested against a copy of the current SQLite schema, and preserve task IDs and artifact paths.

## 7. API and real-time data

### 7.1 REST responsibilities

REST remains authoritative for queries and mutations. The first subproject requires APIs for:

- Paginated task queries with filters, sorting, and full-text search.
- Task summary counts and storage totals.
- Task metadata, tags, archival, deletion, and requeueing.
- Queue snapshots, reordering, priority, pause, resume, and cancellation.
- Bilibili source validation.
- Trusted local-import root browsing and source validation.
- Processing-profile discovery.
- Task creation.
- Task overview, stages, artifacts, safe logs, and recovery actions.

Bulk mutations return per-task results rather than failing the entire request without explanation.

### 7.2 Server-sent events

The backend provides a versioned SSE stream for:

- Task status changes.
- Queue changes.
- Stage progress.
- Artifact readiness.
- Runtime warnings.

Events include stable IDs so the client can resume with Last-Event-ID. The frontend reconnects with bounded backoff and falls back to low-frequency polling when SSE remains unavailable. REST snapshots repair missed or out-of-order events.

### 7.3 Frontend contract generation

The backend OpenAPI schema is the source of truth. Frontend request and response types are generated during development and checked in or deterministically generated in CI. Hand-maintained duplicate canonical-stage and payload definitions are removed once the generated contract is established.

UI-only view models remain handwritten and map from generated transport types.

## 8. State and failure behavior

Failures are shown at the narrowest useful scope:

- Connection or SSE interruption: persistent but non-blocking top banner.
- Single-task failure: affected row and context inspector with recovery actions.
- Field validation: adjacent to the field while preserving input.
- Queue mutation conflict: optimistic state rolls back and refreshes from the returned revision.
- Artifact failure: localized to the affected workspace section.

Technical paths and logs are secondary disclosures. User-facing summaries are safe and actionable. Destructive actions such as source deletion, artifact cleanup, and force termination require explicit confirmation describing the affected data.

The frontend never infers recovery behavior from human-readable summary strings. Stable status, failure-code, readiness, and recovery-action fields drive behavior.

## 9. First subproject delivery boundary

### 9.1 Included

- Repository-level DESIGN.md and semantic design tokens.
- Reusable component primitives and primitive showcase.
- New desktop application shell.
- Task library home.
- Ordered queue management.
- Bilibili and trusted-local-file task creation.
- Task overview with stages, progress, failure recovery, safe logs, and artifacts.
- Visual integration of the existing subtitle, highlight, and confirmed-clip export capabilities.
- Formal schema migrations and current-data conversion.
- Generated OpenAPI frontend contract.
- SSE task/queue/status stream and polling fallback.

### 9.2 Deferred

- Video playback and waveform timeline.
- Subtitle text editing and revision history.
- Visual highlight trimming.
- Export presets and batch export.
- Advanced finished-media library and automated storage policy.
- Authentication, public-internet deployment, and multi-user collaboration.
- Mobile layouts.

### 9.3 Cutover strategy

The new surface is developed under an isolated `/workstation` route tree while the current routes remain unchanged. It becomes the default route tree only after feature parity for:

- Task creation.
- Processing observation.
- Failure recovery.
- Subtitle viewing.
- Highlight confirmation.
- Clip export.

The old frontend is then removed rather than maintained as a permanent second UI.

## 10. Testing and verification

### 10.1 Backend

- Schema migration from representative current databases.
- Pagination, filtering, search, tagging, and bulk operations.
- Atomic queue reorder and revision conflicts.
- Single active GPU job invariant.
- SSE ordering, resume, disconnect, and snapshot repair.
- Trusted-root path containment.
- Retry, cancellation, and recovery action contracts.

### 10.2 Frontend

- Design-token and primitive-state coverage.
- Task table filtering, pagination, selection, and bulk actions.
- Creation drawer for both source kinds.
- Queue optimistic updates and rollback.
- SSE reducer behavior and polling fallback.
- Task overview and recovery action rendering.

### 10.3 End to end

Playwright scenarios use deterministic mocked or fixture-backed APIs and cover:

- Bilibili task creation.
- Local-file task creation.
- Search and pagination.
- Queue reorder and pause/resume.
- Running progress.
- Recoverable failure and retry.
- Subtitle review.
- Highlight confirmation and clip export.

No automated suite downloads models, requires a GPU, or depends on live Bilibili.

### 10.4 Visual and accessibility QA

Every implemented route and its loading, empty, populated, long-text, disconnected, and failed states are inspected at 1280, 1440, and 1920 px widths in real Chromium. Keyboard navigation, focus order, contrast, reduced motion, and screen-reader names are verified before cutover.

## 11. Acceptance criteria

- The operator sees the active GPU job and queue immediately after opening the app.
- Thousands of tasks remain searchable, filterable, sortable, and paginated without loading the complete library into the browser.
- Bilibili and trusted local-file tasks can be created without placeholder controls.
- Queue order, priority, pause, resume, and cancellation are explicit and reliable.
- Common failures are recoverable without reading raw logs.
- Existing subtitle viewing, highlight confirmation, and clip export capabilities remain available.
- No shipped navigation item or control is a placeholder.
- The new UI passes build, unit, integration, E2E, accessibility, and visual QA gates before default cutover.

## 12. Design decisions and rejected alternatives

- **Chosen:** operations table as the task-library home.
  **Rejected as home:** queue Kanban and cover gallery, because they scale less effectively to thousands of operational records. A queue-specific ordered view remains part of the product.

- **Chosen:** three-column cockpit.
  **Rejected:** video-first editor as the global shell and linear stage wizard, because monitoring, recovery, and navigation would become secondary.

- **Chosen:** SSE plus REST snapshots.
  **Rejected:** polling as the primary real-time mechanism and WebSocket command transport, because the required live data is predominantly server-to-client and REST remains simpler for mutations.

- **Chosen:** trusted server-side import roots for local media.
  **Rejected:** implicit browser upload of very large local video files.

- **Chosen:** single-user workstation scope.
  **Rejected:** authentication, tenancy, and public deployment in the redesign roadmap.

## 13. Follow-on specifications

Subprojects 2–4 each receive their own design specification and implementation plan. They must inherit the shell, design tokens, API conventions, event model, accessibility rules, and no-placeholder policy established by subproject 1.
