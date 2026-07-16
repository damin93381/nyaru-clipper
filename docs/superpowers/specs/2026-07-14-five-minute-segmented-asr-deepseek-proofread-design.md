# Five-minute segmented ASR and DeepSeek proofread

## Goal

Prevent long-form WhisperX repetition loops by processing every task as exact five-minute media work segments, then produce one merged and DeepSeek-proofread Chinese/Japanese subtitle artifact for downstream highlight analysis, reports, and exports.

## Scope

The pipeline remains a single-worker, single-GPU workstation workflow. Its canonical top-level stage order remains `ingest → media_prep → asr → translation → highlight → export → report`; the new split, merge, and proofread operations are durable substeps within the existing `media_prep`, `asr`, and `translation` stages.

The feature applies to newly started and retried tasks. It does not rewrite existing completed task artifacts. The original downloaded video remains authoritative and is never replaced by a re-encoded copy.

## User-visible behavior

After ingest, media preparation creates a deterministic five-minute work manifest. Each item has a stable zero-based index, an exact source start and end offset, and a 16 kHz mono WAV path. All but the final item are exactly 300 seconds; the final item ends at the source duration. The original video is retained in `raw/`; the chunk WAV files are the ASR work slices, avoiding duplicate re-encoded video files while preserving the requested five-minute audio boundary.

ASR processes chunks sequentially through the existing one-GPU worker. Each completed chunk persists its own aligned transcript, subtitle, model metadata, elapsed time, and status. A retry reuses validated successful chunks and runs only missing or failed chunks. The merge operation offsets every segment and word timestamp by the chunk source start, retains stable segment IDs, verifies global monotonic order, and writes the canonical merged Chinese artifacts consumed by the translation stage.

Translation reads the chunk manifest, translates only chunks without a valid translation artifact, then merges them in manifest order. The unreviewed merged bilingual files are retained as diagnostics. The public final bilingual JSON and SRT paths keep their established names, but are written only after proofread succeeds. Highlight analysis therefore consumes corrected bilingual captions without a contract change.

The task's stage summary exposes the active substep and chunk counts: preparing chunks, ASR `n/total`, translating `n/total`, merging, and DeepSeek proofread. Logs include chunk index, source time range, artifact path relative to the task root, retries, and model metadata, but never API keys or full request bodies.

## DeepSeek proofread

Proofread is required for the new workflow. It is a constrained bilingual edit, not a transcription replacement: it may fix obvious duplicated loops, punctuation, terminology consistency, and Chinese-to-Japanese meaning when the merged context makes the correction clear. It must preserve every segment ID, start time, end time, ordering, and segment count. If an intended correction is uncertain, it leaves both fields unchanged.

The proofreader receives bounded contiguous batches from the merged bilingual transcript, with adjacent context supplied only as read-only context. Each response must be JSON containing exactly one correction record for every requested segment ID. The backend validates schema, requested-ID equality, ordering, timestamp immutability, non-empty text, and output-size limits before applying a batch. It fails the task rather than silently emitting an unreviewed final artifact when any response is invalid or incomplete.

The first provider is DeepSeek through its OpenAI-compatible `POST /chat/completions` API, using `httpx`, JSON Output, and a non-streaming request. The configured default is `deepseek-v4-flash` in non-thinking mode because the legacy `deepseek-chat` name is scheduled for deprecation on 2026-07-24. `APP_DEEPSEEK_API_KEY` is read only from process environment and never stored in the database, task artifacts, browser API, logs, or reports.

DeepSeek calls retry transient `429`, `500`, and `503` failures with bounded exponential backoff and jitter. Authentication, billing, invalid-request, invalid-parameter, invalid-JSON, or exhausted retry failures terminate the translation stage with a stable failure code and a remediation-oriented summary. A missing API key also fails the proofread substep; it must not silently skip the requested quality gate. Request timeouts are bounded. The provider response and correction audit metadata record only model, batch index, attempt count, token usage when supplied, elapsed time, and changed-segment counts.

## Configuration

The backend exposes these environment-backed settings:

- `APP_MEDIA_CHUNK_SECONDS=300`
- `APP_PROOFREAD_PROVIDER=deepseek`
- `APP_DEEPSEEK_API_KEY` (required for proofread execution)
- `APP_DEEPSEEK_BASE_URL=https://api.deepseek.com`
- `APP_DEEPSEEK_MODEL=deepseek-v4-flash`
- `APP_DEEPSEEK_REQUEST_TIMEOUT_SECONDS=120`
- `APP_DEEPSEEK_MAX_SEGMENTS_PER_REQUEST=80`
- `APP_DEEPSEEK_MAX_RETRIES=3`

The user-facing API does not accept API keys, model names, or arbitrary proofread prompts. These are operator-controlled runtime configuration. The frontend may display configured/unavailable status and stage summaries but must not receive secret values.

## Data and artifacts

All generated state remains under `data/tasks/<task-id>/work/`:

- `media-chunks.json`: source duration, fixed chunk duration, chunk ranges, work-WAV paths, and per-chunk preparation status.
- `asr-chunks/<index>.json` and `.srt`: per-chunk aligned results with chunk-local times.
- `translation-chunks/<index>.json`: per-chunk bilingual results with chunk-local times.
- `asr-segments.json` and `subtitles.zh.srt`: merged Chinese artifacts with source-global times.
- `subtitles.zh-ja.preproofread.json` and `.srt`: merged bilingual diagnostic artifacts before LLM correction.
- `subtitles.zh-ja.json` and `.srt`: validated, canonical proofread output.
- `proofread-audit.json`: non-secret request/result metadata and changed-segment records.

Artifact metadata records the manifest path, chunk counts, completed/reused chunks, model metadata, and proofread provider metadata. Existing consumers retain the canonical final bilingual artifact kinds and filenames. No new database columns or canonical stage names are required; persisted artifacts and task-stage summaries supply the durable run state.

## Failure handling and cancellation

Every chunk write is atomic: write a temporary artifact, validate it, then rename it and update the manifest. A cancelled run stops before beginning the next chunk or proofread request and retains finished chunk artifacts for retry. A failed ASR, translation, merge-validation, or proofread step leaves earlier validated artifacts intact. Retrying from `asr` invalidates only downstream merged and translation/proofread outputs; retrying from `translation` reuses merged ASR chunks and invalidates only translation and proofread outputs.

The merge rejects duplicate IDs, chunk-range mismatches, non-monotonic global timestamps, or malformed artifacts rather than carrying corruption into translation. The proofreader never receives an API key in errors and never gets access to source video or local file paths.

## Verification

Tests use TDD and isolate `ffmpeg`, WhisperX, translation inference, and DeepSeek behind fakes. Coverage includes exact chunk-boundary manifests, final remainder chunks, global timestamp rebasing, partial ASR and translation retry/resume, corrupt cached chunk rejection, merging order, DeepSeek JSON request construction, valid correction application, malformed/empty/ID-mismatched replies, retryable and permanent HTTP failures, missing-key failure, secret redaction, artifact compatibility, cancellation, and downstream highlight consumption of only final proofread captions.

An end-to-end worker test uses a multi-chunk media fixture with fake ASR, translation, and DeepSeek services, asserts the final artifact and report metadata, then repeats from a deliberately interrupted state to prove successful chunks are reused. The release smoke and Chinese/English deployment and operator documentation cover `uv` setup, `APP_DEEPSEEK_API_KEY`, privacy implications of uploading transcript text to DeepSeek, and failure recovery.

## Non-goals

This work does not introduce parallel GPU workers, change the source-video download format, upload source video or audio to DeepSeek, expose a user-editable LLM prompt, move API keys into the browser, alter clip-export time semantics, or retroactively rewrite completed tasks.
