# Bilibili VTuber VOD MVP Workstation

## TL;DR
> **Summary**: Build a LAN-accessible, single-host MVP workstation that accepts one completed Bilibili VOD URL, downloads the source, generates Chinese timed subtitles and Chinese-Japanese bilingual subtitles, proposes highlight candidates, lets the user confirm clips in a WebUI, exports clips, and emits a per-task report.
> **Deliverables**:
> - FastAPI backend with durable task/stage tracking and artifact metadata
> - React/TypeScript WebUI for task submission, task status, subtitle review, highlight confirmation, and artifact downloads
> - BBDown-primary / yt-dlp-fallback ingest pipeline
> - WhisperX ASR/timing pipeline
> - Local Transformers + PyTorch zh→ja translation pipeline
> - PySceneDetect + heuristic highlight candidate engine
> - ffmpeg-based clip export and task report generation
> - Docker Compose deployment, operator manual, wireframes, and processing-flow diagrams
> **Effort**: XL
> **Parallel**: YES - 2 waves
> **Critical Path**: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 10 → 11 → 12

## Context
### Original Request
- Build a package for Bilibili VTuber recording/VOD download, AI-based timing and Chinese-Japanese bilingual translation, automatic highlight capture and clip export, with a LAN-accessible WebUI, PyTorch-preferred AI backend, Git-managed development, and a complete user-facing manual.

### Interview Summary
- Greenfield repository; no existing code, tests, CI, deployment, or manifests.
- MVP scope is **single completed VOD link**, not live recording and not subscriptions.
- Workflow is **manual single-task processing**: submit one link, wait for staged processing, review bilingual subtitles and highlight candidates, confirm clips, export artifacts.
- Highlighting is **AI-assisted candidate generation with user confirmation**, not blind auto-publishing.
- Translation is **local-first** and **Whisper is not the primary translation engine**; use WhisperX for ASR/timing and a separate local text translation model for zh→ja.
- Runtime target is a **single NVIDIA GPU host on a trusted LAN**; CPU is only a degraded fallback.
- UI must be a **single-task workstation now** but leave room for future task lists, batch jobs, subscriptions, and richer editing surfaces.

### Metis Review (gaps addressed)
- Guardrails added: single machine, single GPU-bound worker, single trusted LAN user role, no auth in MVP, no public exposure, no distributed queue.
- Missing defaults resolved: output formats are internal JSON + `.srt` for subtitles and `.mp4` (H.264/AAC) for clip export; task report is Markdown exportable to HTML later; duplicate submission must be idempotent by normalized source URL + source video ID.
- Scope-creep controls added: Gradio is explicitly excluded from the primary UI; highlighting is heuristic-first; docs are limited to one user manual, one operator/developer deployment doc, and one per-task report.
- Edge cases added to plan: private/region-locked sources, missing cookies, no candidate clips found, long VOD resource pressure, partial pipeline failure after artifacts exist, duplicate submissions.
- Unvalidated assumptions converted into explicit implementation checks: downloader fallback, GPU memory limits, task retention behavior, and LAN binding verification.

## Work Objectives
### Core Objective
Produce a decision-complete MVP implementation plan for a single-host Bilibili VOD processing workstation that is reliable, traceable, and modular enough to swap downloaders, ASR providers, translation models, and highlight logic later without changing the WebUI contract.

### Deliverables
- `backend/` Python application using FastAPI, SQLModel/SQLite, and a durable local worker loop
- `web/` React + Vite + TypeScript frontend
- `infra/` Docker Compose deployment and container definitions with NVIDIA runtime support
- `docs/` operator manual, user manual, wireframes, and processing-flow diagrams
- Stage-local artifact tree under `/data/tasks/{task_id}/...`
- Automated backend, frontend, and Playwright smoke coverage for the happy path and failure path

### Definition of Done (verifiable conditions with commands)
- `uv run --project backend pytest backend/tests -q`
- `pnpm --dir web test --run`
- `pnpm --dir web build`
- `docker compose -f infra/docker-compose.yml config`
- `docker compose -f infra/docker-compose.yml up -d --build && curl -f http://127.0.0.1:8000/api/health`
- `pnpm --dir web exec playwright test e2e/task-flow.spec.ts --reporter=line`

### Must Have
- Single-link VOD submission workflow
- Durable task/stage persistence in SQLite
- Task IDs and disk artifacts for every important stage
- Stage-local retries
- BBDown primary with yt-dlp fallback
- WhisperX ASR/timing
- Local Transformers + PyTorch zh→ja translation provider
- Highlight candidate generation with reasons/scores and zero-candidate handling
- User-confirmed ffmpeg clip export
- Per-task Markdown report and user manual
- Trusted-LAN deployment via Docker Compose on a single NVIDIA GPU host

### Must NOT Have
- No live-stream recording support
- No subscriptions or background channel polling
- No multi-user auth/roles
- No public internet exposure
- No fully automatic clip publishing
- No distributed queue, Redis cluster, or multi-host orchestration
- No Gradio as the main UX surface
- No model weight files, downloaded media, or task outputs committed to Git
- No UI behavior coupled to model-specific internals

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: **tests-after** with backend `pytest`, frontend `vitest`, and browser smoke via `playwright`
- QA policy: Every task includes at least one happy-path scenario and one failure/edge-case scenario
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.{ext}`

## Execution Strategy
### Parallel Execution Waves
> Target: 5-8 tasks per wave. Shared foundations are extracted into Wave 1.

Wave 1: foundation and core pipeline capabilities
- 1. Repository/runtime skeleton
- 2. Backend task persistence, stage model, queue, and task APIs
- 3. Bilibili ingest + media prep
- 4. WhisperX ASR + timed Chinese subtitles
- 5. Local Transformers zh→ja translation + bilingual subtitles
- 6. Highlight candidate analysis engine

Wave 2: export, orchestration, UI, docs, and hardening
- 7. Clip export, task report, and retention/cleanup rules
- 8. Pipeline orchestrator, idempotency, and stage-local retry wiring
- 9. Web shell, task submission, and status/detail page
- 10. Subtitle/highlight workspace, candidate confirmation, and artifact downloads
- 11. Docker Compose deployment, manuals, wireframes, and processing-flow docs
- 12. End-to-end validation, LAN binding checks, and release hardening

### Dependency Matrix (full, all tasks)
- 1 blocks 2, 3, 9, 11, 12
- 2 blocks 3, 7, 8, 9, 10, 12
- 3 blocks 4 and 8
- 4 blocks 5 and 8
- 5 blocks 6, 7, 8, 10, 12
- 6 blocks 8, 10, 12
- 7 blocks 8, 10, 12
- 8 blocks 9, 10, 12
- 9 blocks 10 and 12
- 10 blocks 12
- 11 blocks 12
- 12 depends on 1, 2, 5, 6, 8, 9, 10, 11

### Agent Dispatch Summary
- Wave 1 → 6 tasks → `unspecified-high`, `senior-backend`, `senior-frontend`
- Wave 2 → 6 tasks → `unspecified-high`, `visual-engineering`, `writing`

## TODOs
> Implementation + Test = ONE task. Never separate.
> Every task below must be executed with the exact file paths and defaults listed.

- [x] 1. Bootstrap repository, runtime, and container skeleton

  **What to do**:
  - Create the root layout: `backend/`, `web/`, `infra/`, `docs/`, `scripts/`, and `/data` mount conventions documented in Compose.
  - Initialize the project as a Git repository at the workspace root so the later per-task commit strategy is actually executable.
  - Use **Python 3.11 + `uv`** for backend dependency management and **Node 20 + `pnpm`** for frontend.
  - Create `backend/pyproject.toml` with FastAPI, uvicorn, sqlmodel, pydantic-settings, httpx, orjson, pytest, pytest-asyncio.
  - Create a minimal runnable FastAPI entrypoint at `backend/app/main.py` that can import cleanly from day one and will later receive route registration from Task 2.
  - Create `web/` with Vite + React + TypeScript + Vitest + React Testing Library + Playwright config.
  - Add `.gitignore` that excludes `/data/`, model caches, media outputs, `.venv`, `node_modules`, and local env files.
  - Create `infra/docker-compose.yml`, `infra/docker/api.Dockerfile`, and `infra/docker/web.Dockerfile` with NVIDIA runtime support for the backend/worker image and LAN-safe `0.0.0.0` binding.

  **Must NOT do**:
  - Do not download model weights during image build.
  - Do not expose services publicly or add auth.
  - Do not add Redis, Celery, or Prefect in the first pass.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: cross-cutting bootstrap across backend, frontend, and infra.
  - Skills: [`senior-fullstack`, `docker-development`] - bootstrap stack coherence and container hygiene.
  - Omitted: [`playwright-pro`] - browser automation is not the primary work in this task.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 2, 3, 9, 11, 12 | Blocked By: none

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 4, 5.6, 5.8, 5.9, 15
  - FastAPI docs: `https://fastapi.tiangolo.com/`
  - Vite React TS docs: `https://vite.dev/guide/`
  - Docker Compose docs: `https://docs.docker.com/compose/`
  - NVIDIA Container Toolkit docs: `https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/`

  **Acceptance Criteria**:
  - [ ] `uv run --project backend pytest backend/tests/test_smoke.py -q` passes.
  - [ ] `uv run --project backend python -c "from app.main import app; print(app.title)"` exits 0.
  - [ ] `pnpm --dir web test --run src/test/smoke.test.tsx` passes.
  - [ ] `docker compose -f infra/docker-compose.yml config` exits 0.
  - [ ] `git status --short` runs successfully in the workspace root.
  - [ ] `.gitignore` excludes `/data/`, model caches, and generated outputs.

  **QA Scenarios**:
  ```
  Scenario: Bootstrap smoke
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_smoke.py -q`; run `pnpm --dir web test --run src/test/smoke.test.tsx`; run `docker compose -f infra/docker-compose.yml config`.
    Expected: All commands exit 0 and produce evidence logs.
    Evidence: .sisyphus/evidence/task-1-bootstrap-smoke.txt

  Scenario: Compose misconfiguration prevention
    Tool: Bash
    Steps: Run `docker compose -f infra/docker-compose.yml config --quiet` and inspect non-zero exit handling if any service references a missing file.
    Expected: Compose validation passes with no undefined service/build path errors.
    Evidence: .sisyphus/evidence/task-1-bootstrap-config.txt
  ```

  **Commit**: YES | Message: `chore(repo): bootstrap fullstack workspace skeleton` | Files: `backend/**`, `web/**`, `infra/**`, `.gitignore`

- [x] 2. Build durable task persistence, storage layout, and task APIs

  **What to do**:
  - Create SQLite-backed models for `Task`, `TaskStage`, `Artifact`, and `ClipCandidate` under `backend/app/models/`.
  - Implement `backend/app/db.py` and `backend/app/repositories/tasks.py` using SQLModel.
  - Define canonical stage names: `ingest`, `media_prep`, `asr`, `translation`, `highlight`, `export`, `report`.
  - Implement task statuses/stage statuses: `pending`, `running`, `success`, `failed`, `skipped`.
  - Implement `backend/app/services/storage.py` to create `/data/tasks/{task_id}/{raw,work,exports,reports,logs}` and persist artifact metadata.
  - Add FastAPI routes in `backend/app/api/routes/tasks.py` and `health.py` for create task, fetch task detail, fetch stage list, fetch artifact list, fetch log summaries, and a `POST /api/tasks/{task_id}/retry` contract for stage-local retries.
  - Wire `backend/app/main.py` to register the API router and expose a runnable FastAPI server entrypoint for local startup and Docker Compose.
  - Add a single-worker durable queue loop using a SQLite-backed job table plus `backend/app/worker.py`; enforce exactly **one GPU-bound active job at a time**.

  **Must NOT do**:
  - Do not use in-memory queues.
  - Do not add multi-worker GPU concurrency.
  - Do not mix task metadata and artifact files; SQLite holds metadata, `/data` holds files.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: backend foundations and persistence contracts.
  - Skills: [`senior-backend`] - API, storage, queue, and persistence discipline.
  - Omitted: [`senior-frontend`] - no UI work here.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 3, 7, 8, 9, 10, 12 | Blocked By: 1

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 6, 8, 9, 10, 11, 12
  - SQLModel docs: `https://sqlmodel.tiangolo.com/`
  - FastAPI background patterns: `https://fastapi.tiangolo.com/tutorial/background-tasks/`

  **Acceptance Criteria**:
  - [ ] `uv run --project backend pytest backend/tests/test_tasks_api.py backend/tests/test_storage_layout.py -q` passes.
  - [ ] `uv run --project backend python -c "from app.services.storage import ensure_task_dirs; print(sorted(ensure_task_dirs('task-demo').keys()))"` prints the expected directory keys.
  - [ ] `uv run --project backend python -c "from app.main import app; print(sorted([route.path for route in app.routes if route.path.startswith('/api')]))"` includes `/api/health`, `/api/tasks`, and `/api/tasks/{task_id}/retry`.
  - [ ] `curl -f http://127.0.0.1:8000/api/health` returns 200 after local startup.

  **QA Scenarios**:
  ```
  Scenario: Create task and inspect persisted stages
    Tool: Bash
    Steps: Start backend locally; run `TASK_ID=$(curl -s -X POST http://127.0.0.1:8000/api/tasks -H 'Content-Type: application/json' -d '{"source_url":"https://www.bilibili.com/video/BV1xx411c7mD"}' | python -c "import json,sys; print(json.load(sys.stdin)['task_id'])")`; then run `curl -s http://127.0.0.1:8000/api/tasks/$TASK_ID > .sisyphus/evidence/task-2-task.json`.
    Expected: Response contains task_id, normalized URL, queued status, and all canonical stages in `pending`.
    Evidence: .sisyphus/evidence/task-2-create-task.txt

  Scenario: Duplicate submission idempotency
    Tool: Bash
    Steps: Submit the same normalized URL twice; compare returned IDs and dedupe behavior according to the implemented rule.
    Expected: Either the existing open task is returned or the second submission is rejected with a clear duplicate message; no duplicate active jobs are enqueued.
    Evidence: .sisyphus/evidence/task-2-idempotency.txt
  ```

  **Commit**: YES | Message: `feat(api): add task persistence and queue core` | Files: `backend/app/**`, `backend/tests/**`

- [x] 3. Implement Bilibili ingest and media preparation

  **What to do**:
  - Create `backend/app/services/downloader.py` with BBDown primary and yt-dlp fallback adapters using subprocess invocation.
  - Require cookie-based auth support via an env-configured cookie path; record when auth is absent.
  - Normalize downloader results into one contract: source metadata, output file path, selected downloader, and fallback_used flag.
  - Create `backend/app/services/media_prep.py` for `ffprobe` metadata capture and `ffmpeg` audio extraction to a fixed format: mono, 16kHz WAV for ASR input.
  - Persist artifacts and logs under the task tree and mark stages accordingly.
  - Add private/region-locked and downloader-fallback handling.

  **Must NOT do**:
  - Do not let downloader-specific JSON leak into later pipeline stages.
  - Do not skip `ffprobe`; media metadata is mandatory.
  - Do not call yt-dlp first; BBDown remains the default.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: external-tool integration and artifact contract design.
  - Skills: [`senior-backend`] - subprocess integration, error handling, and contracts.
  - Omitted: [`docker-development`] - containerization is already scaffolded and not the main risk here.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 4, 8 | Blocked By: 1, 2

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 5.1, 5.2, 6.1, 6.2
  - BBDown: `https://github.com/nilaoda/BBDown`
  - yt-dlp Bilibili extractor: `https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/bilibili.py`
  - ffmpeg docs: `https://ffmpeg.org/ffmpeg.html`

  **Acceptance Criteria**:
  - [ ] `uv run --project backend pytest backend/tests/test_downloader.py backend/tests/test_media_prep.py -q` passes.
  - [ ] A mocked BBDown failure triggers yt-dlp fallback and records `fallback_used=true` in task metadata.
  - [ ] Media prep emits a 16kHz mono WAV path and ffprobe metadata artifact.

  **QA Scenarios**:
  ```
  Scenario: BBDown happy path with normalized artifacts
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_downloader.py::test_bbdown_success backend/tests/test_media_prep.py::test_extract_audio_success -q`.
    Expected: Source metadata, raw video artifact, ffprobe metadata, and normalized WAV artifact are recorded.
    Evidence: .sisyphus/evidence/task-3-ingest-happy.txt

  Scenario: Fallback to yt-dlp after BBDown failure
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_downloader.py::test_falls_back_to_ytdlp -q`.
    Expected: The task does not fail if BBDown exits non-zero and yt-dlp succeeds; fallback is visible in task logs.
    Evidence: .sisyphus/evidence/task-3-ingest-fallback.txt
  ```

  **Commit**: YES | Message: `feat(ingest): add bbdown download with ytdlp fallback` | Files: `backend/app/services/downloader.py`, `backend/app/services/media_prep.py`, `backend/tests/**`

- [x] 4. Implement WhisperX ASR and timed Chinese subtitle generation

  **What to do**:
  - Create `backend/app/services/asr_whisperx.py` to load one WhisperX model configuration from settings and run transcription/alignment on the normalized WAV artifact.
  - Create `backend/app/services/subtitles.py` to transform aligned transcript segments into internal JSON and `.srt` output.
  - Persist segment IDs, start/end timestamps, text, optional word timings, model metadata, and elapsed time.
  - Add explicit failure handling for missing model files, OOM, and alignment failures.
  - Ensure the ASR stage can be retried without re-running ingest/media prep if those artifacts exist.

  **Must NOT do**:
  - Do not call WhisperX directly from API routes.
  - Do not make `.ass` mandatory in MVP; internal JSON + `.srt` is the default output contract.
  - Do not discard the raw alignment JSON.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: GPU-bound model integration with artifact persistence.
  - Skills: [`senior-ml-engineer`, `senior-backend`] - model loading and robust backend integration.
  - Omitted: [`senior-frontend`] - no UI work.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 5, 8 | Blocked By: 3

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 5.3, 6.3, 11
  - WhisperX: `https://github.com/m-bain/whisperX`

  **Acceptance Criteria**:
  - [ ] `uv run --project backend pytest backend/tests/test_asr_whisperx.py backend/tests/test_subtitles.py -q` passes.
  - [ ] ASR stage stores aligned transcript JSON and `.srt` under the task directory.
  - [ ] Missing-model and OOM errors are classified as terminal config/runtime failures with actionable messages.

  **QA Scenarios**:
  ```
  Scenario: ASR happy path on fixture audio
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_asr_whisperx.py::test_transcribe_fixture_audio backend/tests/test_subtitles.py::test_generate_srt_from_segments -q`.
    Expected: Segment JSON and `.srt` artifacts are generated with ordered timestamps.
    Evidence: .sisyphus/evidence/task-4-asr-happy.txt

  Scenario: Missing model failure classification
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_asr_whisperx.py::test_missing_model_is_terminal -q`.
    Expected: Stage ends in `failed`, error message instructs the operator to provision the model, and retry is not auto-attempted.
    Evidence: .sisyphus/evidence/task-4-asr-missing-model.txt
  ```

  **Commit**: YES | Message: `feat(asr): add whisperx timed transcription pipeline` | Files: `backend/app/services/asr_whisperx.py`, `backend/app/services/subtitles.py`, `backend/tests/**`

- [x] 5. Implement local zh→ja translation and bilingual subtitle outputs

  **What to do**:
  - Create `backend/app/services/translation_provider.py` as the stable interface and `backend/app/services/translation_hf.py` as the Hugging Face implementation.
  - Default to one configured zh→ja model family (start with `facebook/nllb-200-distilled-600M` unless GPU memory tests force a smaller default) and document the fallback model option in config.
  - Translate per subtitle segment, preserving original segment IDs and timestamps.
  - Emit bilingual JSON and bilingual `.srt` with Chinese line first and Japanese line second for each segment.
  - Record translation model metadata, elapsed time, and failure classification.

  **Must NOT do**:
  - Do not use Whisper/WhisperX direct translation as the primary path.
  - Do not merge or re-split subtitle segments in the translation stage.
  - Do not drop untranslated failures silently; preserve per-segment failure handling and stage failure reporting.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: model/provider abstraction with subtitle contract preservation.
  - Skills: [`senior-ml-engineer`, `senior-backend`] - local PyTorch inference and service boundaries.
  - Omitted: [`llm-cost-optimizer`] - this is local inference, not API spend control.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 6, 7, 8, 10, 12 | Blocked By: 4

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 5.4, 6.4
  - Transformers docs: `https://huggingface.co/docs/transformers/index`
  - NLLB model docs: `https://huggingface.co/facebook/nllb-200-distilled-600M`

  **Acceptance Criteria**:
  - [ ] `uv run --project backend pytest backend/tests/test_translation_hf.py backend/tests/test_bilingual_subtitles.py -q` passes.
  - [ ] Translation output preserves segment IDs/timestamps from ASR JSON.
  - [ ] Bilingual `.srt` contains paired Chinese + Japanese lines for each segment.

  **QA Scenarios**:
  ```
  Scenario: Segment-preserving bilingual subtitle generation
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_translation_hf.py::test_translate_segments backend/tests/test_bilingual_subtitles.py::test_emit_bilingual_srt -q`.
    Expected: The output `.srt` keeps the original timestamps while inserting Japanese text under the Chinese source line.
    Evidence: .sisyphus/evidence/task-5-translation-happy.txt

  Scenario: Translation provider error handling
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_translation_hf.py::test_translation_runtime_failure_marks_stage_failed -q`.
    Expected: Runtime failure is surfaced with the model name, task remains resumable from translation onward, and prior ASR artifacts remain intact.
    Evidence: .sisyphus/evidence/task-5-translation-failure.txt
  ```

  **Commit**: YES | Message: `feat(translation): add local zh-ja subtitle translation` | Files: `backend/app/services/translation_provider.py`, `backend/app/services/translation_hf.py`, `backend/tests/**`

- [x] 6. Implement highlight candidate analysis

  **What to do**:
  - Create `backend/app/services/highlights.py` and `highlight_scoring.py`.
  - Use `PySceneDetect` scene boundaries plus heuristics from subtitle density, punctuation/emphasis tokens, repeated laughter/excitement phrases, and optional audio-energy deltas from ffmpeg-extracted metrics.
  - Score and rank candidate windows; persist reason codes, source signals, score breakdown, and default clip ranges.
  - Enforce explicit behavior when no strong candidate exists: persist an empty candidate list with a `no_candidates` explanation instead of failing the stage.

  **Must NOT do**:
  - Do not hide zero-candidate outcomes.
  - Do not export clips in this task.
  - Do not introduce a neural highlight model in MVP.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: mixed signal fusion and deterministic heuristics.
  - Skills: [`senior-backend`] - deterministic scoring and persistence.
  - Omitted: [`senior-ml-engineer`] - no new trainable model is being added here.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 8, 10, 12 | Blocked By: 5

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 5.5, 6.5
  - PySceneDetect docs: `https://www.scenedetect.com/docs/latest/`

  **Acceptance Criteria**:
  - [ ] `uv run --project backend pytest backend/tests/test_highlights.py -q` passes.
  - [ ] Candidate JSON includes `start_s`, `end_s`, `score`, `reasons`, and `status` fields.
  - [ ] Empty-result runs end in `success` with a persisted zero-candidate artifact.

  **QA Scenarios**:
  ```
  Scenario: Candidate generation from timed subtitles
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_highlights.py::test_generates_ranked_candidates -q`.
    Expected: At least one ranked candidate is produced from the fixture transcript and scene boundaries.
    Evidence: .sisyphus/evidence/task-6-highlights-happy.txt

  Scenario: No-candidate path
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_highlights.py::test_no_candidate_is_success_not_failure -q`.
    Expected: The stage finishes successfully with an empty candidate artifact and a human-readable explanation.
    Evidence: .sisyphus/evidence/task-6-highlights-empty.txt
  ```

  **Commit**: YES | Message: `feat(highlights): score candidate clips from subtitles and scenes` | Files: `backend/app/services/highlights.py`, `backend/tests/test_highlights.py`

- [x] 7. Implement clip export, task report generation, and retention rules

  **What to do**:
  - Create `backend/app/services/clip_export.py` to export confirmed ranges to MP4 (`libx264` + `aac`) with deterministic filenames.
  - Accept user-adjusted `start_s`/`end_s` values and validate them against source duration.
  - Create `backend/app/services/reporting.py` to generate per-task Markdown reports containing input, source metadata, stage timings, models, errors/retries, artifacts, and exported clips.
  - Create `backend/app/services/cleanup.py` to prune transient work artifacts after success while keeping `raw/`, `exports/`, `reports/`, subtitles, and manifest metadata.
  - Add the backend write endpoint contract in `backend/app/api/routes/tasks.py` for `POST /api/tasks/{task_id}/clips` so the UI can confirm a candidate and trigger export.

  **Must NOT do**:
  - Do not burn subtitles into the clip in MVP.
  - Do not delete raw source video automatically.
  - Do not let cleanup remove task manifests, reports, subtitles, or logs.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: output correctness, retention, and reporting are tightly coupled.
  - Skills: [`senior-backend`, `roadmap-communicator`] - implementation plus polished report output.
  - Omitted: [`senior-frontend`] - no UI work.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 8, 10, 12 | Blocked By: 2, 5

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 6.6, 6.7, 14
  - ffmpeg docs: `https://ffmpeg.org/ffmpeg.html`

  **Acceptance Criteria**:
  - [ ] `uv run --project backend pytest backend/tests/test_clip_export.py backend/tests/test_reporting.py backend/tests/test_cleanup.py -q` passes.
  - [ ] Confirmed clip exports are written under `/data/tasks/{task_id}/exports/` with stable filenames.
  - [ ] Task report Markdown contains source metadata, stage timings, model metadata, retries, and artifact links.
  - [ ] `uv run --project backend pytest backend/tests/test_clip_export_api.py -q` passes.

  **QA Scenarios**:
  ```
  Scenario: Export confirmed clip range
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_clip_export.py::test_export_confirmed_range -q`.
    Expected: An MP4 file is created with the requested bounds and metadata recorded in SQLite.
    Evidence: .sisyphus/evidence/task-7-export-happy.txt

  Scenario: Reject invalid adjusted range
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_clip_export.py::test_rejects_out_of_bounds_range -q`.
    Expected: Invalid ranges are rejected with a clear validation error and no file is exported.
    Evidence: .sisyphus/evidence/task-7-export-invalid-range.txt
  ```

  **Commit**: YES | Message: `feat(outputs): add clip export reporting and cleanup rules` | Files: `backend/app/services/clip_export.py`, `backend/app/services/reporting.py`, `backend/tests/**`

- [x] 8. Wire the end-to-end pipeline orchestrator, retries, and idempotency rules

  **What to do**:
  - Create `backend/app/services/task_runner.py` to execute the canonical stage order and checkpoint after each successful stage.
  - Implement stage-local resume: if prior artifacts and successful stage records exist, re-run only the failed stage and downstream stages.
  - Define task idempotency on normalized source URL + discovered source video ID; if an active task exists for the same source, return it instead of enqueuing a duplicate.
  - Surface user-visible error summaries and detailed logs per stage.
  - Add queue-worker integration so task submission triggers exactly one durable background run and `POST /api/tasks/{task_id}/retry` requeues only the failed stage/downstream path.

  **Must NOT do**:
  - Do not recompute successful upstream stages on retry.
  - Do not allow more than one active GPU-bound task.
  - Do not hide intermediate stage transitions from the API.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: orchestration logic, failure semantics, and idempotency are the system’s hardest correctness points.
  - Skills: [`systematic-debugging`, `senior-backend`] - stage transition safety and retry correctness.
  - Omitted: [`senior-frontend`] - orchestration only.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 9, 10, 12 | Blocked By: 2, 3, 4, 5, 6, 7

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 8, 10, 11, 12, 13
  - Existing planned contracts from tasks 2-7

  **Acceptance Criteria**:
  - [ ] `uv run --project backend pytest backend/tests/test_task_runner.py backend/tests/test_retry_resume.py -q` passes.
  - [ ] Retrying a failed translation task does not rerun ingest/media/asr.
  - [ ] Submitting the same active VOD twice does not create two active jobs.
  - [ ] `uv run --project backend pytest backend/tests/test_retry_api.py -q` passes.

  **QA Scenarios**:
  ```
  Scenario: Resume from failed stage
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_retry_resume.py::test_resume_from_translation_failure -q`.
    Expected: Only the failed stage and downstream stages rerun; prior stage timestamps remain unchanged.
    Evidence: .sisyphus/evidence/task-8-retry-resume.txt

  Scenario: Active-task deduplication
    Tool: Bash
    Steps: Run `uv run --project backend pytest backend/tests/test_task_runner.py::test_duplicate_submission_returns_existing_task -q`.
    Expected: The second submission references the existing active task instead of creating a new worker job.
    Evidence: .sisyphus/evidence/task-8-idempotency.txt
  ```

  **Commit**: YES | Message: `feat(orchestration): add resumable staged task runner` | Files: `backend/app/services/task_runner.py`, `backend/tests/**`

- [x] 9. Build the WebUI shell, task submission flow, and task detail/status page

  **What to do**:
  - Create `web/src/lib/api.ts`, `web/src/lib/types.ts`, `web/src/router.tsx`, and a TanStack Query-based API client.
  - Create `web/src/pages/NewTaskPage.tsx` with `data-testid="task-url-input"`, `data-testid="task-submit-button"`, and option toggles for translation/highlight/export.
  - Create `web/src/pages/TaskDetailPage.tsx` with a stage timeline, user-readable log summaries, and artifact overview.
  - Create Playwright specs `web/e2e/task-submit.spec.ts` and `web/e2e/task-detail.spec.ts` for the submission and failure-detail flows used by this task’s QA scenarios.
  - Use polling for task detail updates; 3s interval while running, 15s after terminal state.
  - Reserve layout regions for future task lists and workspace expansion without implementing them now.

  **Must NOT do**:
  - Do not add subscription or history pages in MVP.
  - Do not hardcode model/provider names into UI logic beyond display labels returned by the API.
  - Do not build a modal-heavy flow; keep the workstation page-oriented.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: UX structure matters and future expansion space must be preserved.
  - Skills: [`senior-frontend`] - React state, polling, and ergonomic workstation UX.
  - Omitted: [`epic-design`] - aesthetics are secondary to operational clarity.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 10, 12 | Blocked By: 1, 2, 8

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 7, 12, 16
  - React docs: `https://react.dev/`
  - TanStack Query docs: `https://tanstack.com/query/latest`

  **Acceptance Criteria**:
  - [ ] `pnpm --dir web test --run src/pages/__tests__/NewTaskPage.test.tsx src/pages/__tests__/TaskDetailPage.test.tsx` passes.
  - [ ] Submitting a valid URL from the UI triggers task creation and navigation to the detail page.
  - [ ] Task detail shows all canonical stages and terminal failure summaries.

  **QA Scenarios**:
  ```
  Scenario: Submit task from UI and land on detail page
    Tool: Playwright
    Steps: Run `pnpm --dir web exec playwright test e2e/task-submit.spec.ts --grep @happy --reporter=line`.
    Expected: The test submits a fixture URL, lands on `/tasks/<generated-id>`, and asserts the full stage timeline is visible.
    Evidence: .sisyphus/evidence/task-9-ui-submit.png

  Scenario: Show failure summary on detail page
    Tool: Playwright
    Steps: Run `pnpm --dir web exec playwright test e2e/task-detail.spec.ts --grep @translation-failed --reporter=line`.
    Expected: The test loads a failed fixture task and asserts that the `translation` stage renders as failed with a readable summary and retry-ready state.
    Evidence: .sisyphus/evidence/task-9-ui-failure.png
  ```

  **Commit**: YES | Message: `feat(web): add task submission and status workstation shell` | Files: `web/src/**`, `web/tests/**`

- [x] 10. Implement subtitle/highlight workspace, candidate confirmation, and downloads

  **What to do**:
  - Create `web/src/pages/WorkspacePage.tsx` or extend `TaskDetailPage` with a dedicated workspace panel.
  - Render timed Chinese subtitles and bilingual subtitles side-by-side using API-provided segment IDs.
  - Render highlight candidates in a ranked list with score, reasons, default time range, and editable `start/end` fields.
  - Add `data-testid="candidate-confirm-button"`, `data-testid="candidate-start-input"`, `data-testid="candidate-end-input"`, and download buttons for subtitle/report/clip artifacts.
  - Integrate confirm-export action with backend clip export endpoint and show resulting artifact cards.
  - Create Playwright spec `web/e2e/workspace.spec.ts` for the candidate export and zero-candidate states used by this task’s QA scenarios.

  **Must NOT do**:
  - Do not implement a drag timeline editor in MVP.
  - Do not auto-export clips on task completion.
  - Do not hide the zero-candidate state.

  **Recommended Agent Profile**:
  - Category: `visual-engineering` - Reason: workspace usability and confirmation flow are the primary UI value.
  - Skills: [`senior-frontend`] - stateful review UI and artifact actions.
  - Omitted: [`playwright-pro`] - browser tests are verification, not implementation guidance.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 12 | Blocked By: 2, 5, 6, 7, 8, 9

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 6.5, 6.6, 7, 14
  - Planned API contracts from tasks 5-9

  **Acceptance Criteria**:
  - [ ] `pnpm --dir web test --run src/pages/__tests__/WorkspacePage.test.tsx` passes.
  - [ ] Workspace renders bilingual subtitles, ranked highlight candidates, and zero-candidate empty state.
  - [ ] Confirming a candidate triggers export and exposes a downloadable MP4 artifact card.

  **QA Scenarios**:
  ```
  Scenario: Confirm candidate and export clip
    Tool: Playwright
    Steps: Run `pnpm --dir web exec playwright test e2e/workspace.spec.ts --grep @export-candidate --reporter=line`.
    Expected: The test loads a fixture task with candidates, edits the range, confirms export, and asserts that a downloadable clip card appears.
    Evidence: .sisyphus/evidence/task-10-workspace-export.png

  Scenario: Zero-candidate UX
    Tool: Playwright
    Steps: Run `pnpm --dir web exec playwright test e2e/workspace.spec.ts --grep @zero-candidate --reporter=line`.
    Expected: The test loads a zero-candidate fixture task and asserts the empty state plus subtitle/report downloads remain visible.
    Evidence: .sisyphus/evidence/task-10-workspace-empty.png
  ```

  **Commit**: YES | Message: `feat(web): add subtitle and highlight review workspace` | Files: `web/src/**`, `web/tests/**`

- [x] 11. Add deployment assets, manuals, wireframes, and processing-flow docs

  **What to do**:
  - Create `docs/user-manual.md` for end users.
  - Create `docs/operator-manual.md` for setup, cookies, model provisioning, GPU requirements, and LAN binding.
  - Create `docs/wireframes.md` with text-first annotated wireframes for the four MVP screens.
  - Create `docs/processing-flow.md` with one Mermaid or ASCII diagram of the canonical stage flow and one artifact tree diagram.
  - Finish Docker Compose service definitions for `api`, `worker`, and `web`, including volume mounts for `/data` and model cache directories.
  - Document trusted-LAN-only assumptions and explicit non-support for public deployment.

  **Must NOT do**:
  - Do not create a docs site or multiple fragmented manuals.
  - Do not document unsupported flows such as live recording or subscriptions as if they already exist.
  - Do not omit cookie/auth setup caveats for Bilibili access.

  **Recommended Agent Profile**:
  - Category: `writing` - Reason: this task is documentation-heavy with some deployment finishing.
  - Skills: [`roadmap-communicator`, `senior-devops`] - clear docs plus Compose correctness.
  - Omitted: [`content-production`] - this is product/ops documentation, not marketing copy.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: 12 | Blocked By: 1

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 7, 14, 15, 16, 17
  - Docker Compose docs: `https://docs.docker.com/compose/`
  - Mermaid docs: `https://mermaid.js.org/`

  **Acceptance Criteria**:
  - [ ] `python -m py_compile backend/app/main.py` still passes after Compose/doc changes.
  - [ ] `docker compose -f infra/docker-compose.yml config` passes.
  - [ ] `docs/user-manual.md`, `docs/operator-manual.md`, `docs/wireframes.md`, and `docs/processing-flow.md` all exist and reflect the implemented MVP only.

  **QA Scenarios**:
  ```
  Scenario: Manual completeness sweep
    Tool: Bash
    Steps: Run `test -f docs/user-manual.md && test -f docs/operator-manual.md && test -f docs/wireframes.md && test -f docs/processing-flow.md`; then run `grep -q 'single-link' docs/user-manual.md && grep -q 'LAN' docs/operator-manual.md && grep -q 'task report' docs/user-manual.md && grep -q 'clip' docs/wireframes.md`.
    Expected: All required docs are present and aligned with implemented scope.
    Evidence: .sisyphus/evidence/task-11-docs-check.txt

  Scenario: Compose deployment sweep
    Tool: Bash
    Steps: Run `docker compose -f infra/docker-compose.yml config` and inspect service definitions for `api`, `worker`, and `web` plus `/data` mounts.
    Expected: Compose parses cleanly and includes the required volumes and host bindings.
    Evidence: .sisyphus/evidence/task-11-compose-check.txt
  ```

  **Commit**: YES | Message: `docs(mvp): add manuals wireframes and processing flow` | Files: `docs/**`, `infra/docker-compose.yml`

- [x] 12. Run end-to-end hardening, LAN checks, and release smoke tests

  **What to do**:
  - Add `backend/tests/test_e2e_pipeline.py` for a fixture-driven backend smoke pipeline.
  - Add `web/e2e/task-flow.spec.ts` for the browser happy path and failure path.
  - Add `scripts/release_smoke.sh` to seed fixture artifacts, start Compose, and run smoke commands in sequence.
  - Add `scripts/seed_failure_fixture.py` to create a deterministic failed-translation task for browser failure-path verification.
  - Verify LAN-safe binding (`0.0.0.0`) in Compose and API startup.
  - Confirm the happy path and failure path both generate evidence artifacts in `.sisyphus/evidence/`.

  **Must NOT do**:
  - Do not rely on live Bilibili network access for automated smoke tests.
  - Do not skip browser coverage for the submission → review → export flow.
  - Do not leave `TODO` placeholders in release scripts or docs.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: final integration requires backend, frontend, and deployment coordination.
  - Skills: [`verification-before-completion`, `senior-qa`, `playwright-pro`] - evidence-first release validation.
  - Omitted: [`senior-frontend`] - implementation is complete; this is integration hardening.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: none | Blocked By: 1, 2, 5, 6, 8, 9, 10, 11

  **References**:
  - Spec: `.sisyphus/drafts/bilibili-vtuber-suite-spec.md` - sections 13, 17
  - Planned contracts and selectors from tasks 2, 8, 9, 10, 11

  **Acceptance Criteria**:
  - [ ] `uv run --project backend pytest backend/tests/test_e2e_pipeline.py -q` passes.
  - [ ] `pnpm --dir web exec playwright test e2e/task-flow.spec.ts --reporter=line` passes.
  - [ ] `docker compose -f infra/docker-compose.yml up -d --build && curl -f http://127.0.0.1:8000/api/health` passes.
  - [ ] Compose exposes services on `0.0.0.0` rather than `127.0.0.1` only.

  **QA Scenarios**:
  ```
  Scenario: Full happy-path smoke
    Tool: Bash
    Steps: Run `bash scripts/release_smoke.sh`; then run `pnpm --dir web exec playwright test e2e/task-flow.spec.ts --grep @happy --reporter=line`.
    Expected: One fixture task reaches terminal success, exports a clip, and produces a report.
    Evidence: .sisyphus/evidence/task-12-happy-path.txt

  Scenario: Failure-path smoke
    Tool: Playwright
    Steps: Run `uv run --project backend python scripts/seed_failure_fixture.py --stage translation --output .sisyphus/evidence/task-12-failure-fixture.json`; then run `pnpm --dir web exec playwright test e2e/task-flow.spec.ts --grep @translation-failed --reporter=line`.
    Expected: The UI shows the failed stage, readable summary, and retry-ready state without corrupting prior artifacts.
    Evidence: .sisyphus/evidence/task-12-failure-path.png
  ```

  **Commit**: YES | Message: `test(release): add end-to-end smoke and hardening checks` | Files: `backend/tests/**`, `web/e2e/**`, `scripts/**`

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [x] F1. Plan Compliance Audit — oracle
- [x] F2. Code Quality Review — unspecified-high
- [x] F3. Real Manual QA — unspecified-high (+ playwright if UI)
- [x] F4. Scope Fidelity Check — deep

## Commit Strategy
- Use one conventional commit per numbered task.
- Keep docs/manual/diagram changes in the same commit as the feature they explain only when they are inseparable; otherwise use the dedicated docs task commit.
- Never commit `/data/**`, model weights, downloaded media, generated clips, caches, or `.sisyphus/evidence/**`.
- If a task spans backend and frontend, commit once after both sides and tests pass for that task.

## Success Criteria
- The repository can be bootstrapped on a single NVIDIA GPU host with Docker Compose.
- One Bilibili VOD URL can be submitted from the WebUI and processed end-to-end.
- The system persists all critical artifacts by `task_id` and supports stage-local retries.
- The UI exposes task status, bilingual subtitles, highlight candidates, candidate confirmation, and artifact downloads.
- The system exports deterministic MP4 clips and Markdown task reports.
- User-facing and operator-facing docs exist, including wireframes and processing-flow diagrams.
- Automated backend, frontend, and browser checks pass.
