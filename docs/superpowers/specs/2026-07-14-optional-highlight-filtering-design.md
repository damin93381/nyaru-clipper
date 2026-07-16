# Optional automatic highlight filtering

## Goal

Let the operator decide, for each newly created workstation task, whether the automatic highlight-filtering stage runs. The default is **off** so the normal workload stops after transcription and translation unless the operator explicitly requests ranked clip candidates.

## User experience

The task-creation drawer keeps the existing processing profile and priority controls and adds an "Enable automatic highlight filtering" switch. It is off when the drawer opens. The control explains that enabling it creates ranked candidate clips; leaving it off saves the highlight-analysis work.

The selected value is submitted with the v2 task-creation request and returned in its response. A task overview exposes the immutable selection so the operator can tell why a pipeline stage was skipped.

When disabled, the pipeline continues through ingest, media preparation, ASR, translation, the user-confirmed export checkpoint, and report generation. Its canonical `highlight` stage is recorded as `skipped` with a clear user-visible summary. No highlight candidate artifact or `ClipCandidate` records are created. The review workspace states that automatic candidates were disabled, rather than reporting a missing artifact or an empty highlight result.

Existing and legacy-created tasks retain the historical behavior: automatic highlight filtering is enabled unless their task record explicitly says otherwise. Retrying a task retains its original selection.

## Architecture

Add a boolean `highlight_filtering_enabled` field to `Task`, defaulting to `true` at the persistence layer for backward compatibility. An Alembic migration adds the non-null column with that server default so existing SQLite task rows are enabled without manual intervention.

The v2 `CreateWorkstationTaskRequest` and response carry the boolean. The v2 creation path persists it on the new task. The legacy endpoint remains compatible and continues to create enabled tasks.

The task runner wraps only the `highlight` executor: when the persisted option is false it returns a `StageDirective(status="skipped", ...)`; otherwise it calls the existing analyzer. The canonical seven-stage order remains unchanged, preserving queue, progress, retry, run-history, and report contracts. Artifact-readiness projection treats the deliberately skipped highlight stage as not applicable, rather than missing.

## Error handling and compatibility

The option is immutable once queued. This avoids changing a pipeline under a worker and guarantees retry reproducibility. Invalid request values remain rejected by the API schema. Existing task data and v1 clients continue to work without supplying the field.

No manual arbitrary-range clip-export workflow is added in this change. A task with automatic filtering disabled has no candidate cards to confirm; enabling candidate generation is the explicit way to use the existing candidate-based export flow.

## Verification

Automated coverage will prove the default-off v2 request, persistence, legacy fallback, skipped-stage pipeline behavior, StageRun mirroring, artifact-readiness projection, and task-creation/review UI states. The regenerated OpenAPI contract and TypeScript client will be checked. Finally, the desktop task drawer and a disabled task overview will be visually inspected in the running application.
