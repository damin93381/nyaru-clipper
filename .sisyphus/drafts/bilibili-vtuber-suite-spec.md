# Bilibili VTuber VOD Processing Workstation - Design Spec

## 1. Summary

Build a LAN-accessible, single-host MVP workstation for processing a single Bilibili VTuber VOD link end-to-end: download the VOD, run ASR with subtitle timing, generate Chinese-Japanese bilingual subtitles, detect highlight candidates, allow the user to confirm candidate clips in a WebUI, export clips, and generate a task report.

The system is intentionally designed as a **Python monolith with modular boundaries**, optimized for a single NVIDIA GPU host on an internal network. The MVP prioritizes reliability, traceability, and reuse of mature OSS components over perfect translation quality or fully automatic clip publishing.

## 2. Confirmed Product Scope

### In Scope
- Input a single completed Bilibili VOD/recording URL manually
- Download the source video using mature existing tools
- Extract and normalize audio for downstream AI processing
- Run Chinese ASR with timing/alignment
- Produce Chinese-Japanese bilingual subtitle outputs
- Detect highlight **candidates** automatically
- Let the user review and confirm candidate clips in a WebUI
- Export confirmed clips
- Export a task-level processing report
- Provide a complete user-facing manual
- Run on an internal network with WebUI access from other LAN devices
- Prefer local, self-hosted, PyTorch-based AI inference
- Use Git throughout development for traceability

### Out of Scope for MVP
- Live stream recording while a stream is in progress
- Continuous channel/room subscription monitoring
- Multi-user auth and permissions
- Public internet multi-tenant SaaS deployment
- Advanced timeline editor or NLE-like editing UX
- Fully automatic publish-ready clipping without human confirmation
- Cloud API dependency as the primary path

## 3. Success Criteria

The MVP is successful only if all of the following are true:
- A user can submit a valid Bilibili VOD link from the WebUI
- The system downloads the source video and shows progress by stage
- The system generates Chinese subtitles with usable timing
- The system generates Chinese-Japanese bilingual subtitle outputs
- The system produces highlight candidate ranges with explanations/scores
- The user can confirm at least one candidate and export a clip
- The system exports a task report describing inputs, outputs, models, timing, and failures/retries
- The WebUI is reachable from another machine on the same LAN
- Failures are visible by stage and can be retried from the failed stage

## 4. Recommended Architecture

### Architecture Style
A **single-host Python monolith** with internal module boundaries and a lightweight job execution layer.

This is not a multi-service system. The host runs one application stack with:
- API/backend
- UI
- worker/job execution
- local storage for artifacts
- local AI inference

### Why This Architecture
- Minimizes MVP infrastructure complexity
- Fits the confirmed single-link manual workflow
- Makes it easier to reuse mature CLI and Python tools together
- Keeps future migration paths open if job execution later needs separation
- Avoids premature microservice complexity

## 5. Concrete Technology Decisions

### 5.1 VOD Download
- **Primary**: `BBDown`
- **Fallback**: `yt-dlp`

Reasoning:
- BBDown is more Bilibili-specific and better aligned with the product target
- yt-dlp provides a resilient fallback when Bilibili extractor behavior changes

### 5.2 Media Processing
- `ffmpeg` for:
  - audio extraction
  - audio normalization
  - clip cutting/export
  - subtitle muxing if needed
- `ffprobe` for media inspection metadata

### 5.3 ASR and Timing
- **Primary**: `WhisperX`
- **Reserved future alternative**: `FunASR`

Reasoning:
- WhisperX best matches the confirmed MVP need: transcription + alignment/timestamps
- FunASR remains a future enhancement path for Chinese-heavy optimization, not the initial default

### 5.4 Translation
- **Primary**: local `Transformers` + PyTorch inference
- Model family candidates: `NLLB`, `M2M100`, `mBART-50`

Important decision:
- Whisper/WhisperX is used for **ASR/timing**, not as the main Chinese→Japanese translation engine

Reasoning:
- The product needs subtitle-grade bilingual output, not only raw speech translation
- ASR and translation must remain independently replaceable

### 5.5 Highlight Candidate Detection
- `PySceneDetect` for scene boundaries
- Heuristic scoring on top of:
  - subtitle density
  - emotionally strong phrases / exclamations / repetition
  - speech rate or audio-energy spikes
  - scene changes
- `ffmpeg` for final clip export

Important decision:
- MVP outputs **candidate clips**, not blindly finalized clips

### 5.6 Backend
- `FastAPI` as the application backend

Responsibilities:
- task creation and orchestration endpoints
- stage status exposure
- artifact metadata access
- report export
- UI-serving integration or API consumption by a separate frontend

### 5.7 Job Execution
- Lightweight in-app job queue / worker boundary in MVP
- Design should keep a clean seam for future `Prefect` adoption if richer orchestration is needed

Important decision:
- Do not force heavy orchestration infrastructure into the first working version

### 5.8 WebUI
- WebUI built as a proper application frontend over stable backend contracts
- Do **not** make Gradio the primary product UI
- Gradio may be used later for internal diagnostics or model testing, not for the core product surface

### 5.9 Deployment
- Single NVIDIA GPU host on LAN
- Preferred packaging: `Docker Compose`
- CPU-only mode is not a primary target; CPU is a degraded fallback path only

## 6. Module Boundaries

The monolith must still be decomposed into clear modules.

### 6.1 Ingest Module
Responsibilities:
- validate Bilibili URL input
- resolve download strategy
- invoke BBDown or yt-dlp
- capture source metadata

Outputs:
- original video file
- source metadata JSON

### 6.2 Media Prep Module
Responsibilities:
- inspect media
- extract and normalize audio
- prepare standard downstream formats

Outputs:
- normalized audio file
- media probe metadata

### 6.3 ASR Module
Responsibilities:
- run WhisperX transcription
- produce timed Chinese transcript data
- preserve segment/word timing structures

Outputs:
- transcript JSON
- subtitle segments
- timed Chinese subtitle file(s)

### 6.4 Translation Module
Responsibilities:
- translate Chinese subtitle segments into Japanese
- preserve alignment to subtitle segment IDs/time ranges
- produce bilingual subtitle outputs

Outputs:
- bilingual JSON
- bilingual subtitle file(s)
- translation metadata

### 6.5 Highlight Analysis Module
Responsibilities:
- score candidate highlight ranges
- attach reasons, confidence, source signals
- return user-reviewable candidates

Outputs:
- candidate list JSON

### 6.6 Clip Export Module
Responsibilities:
- accept confirmed candidate ranges
- optionally allow user-adjusted ranges
- export clips using ffmpeg

Outputs:
- clip video files
- clip export record metadata

### 6.7 Report/Documentation Module
Responsibilities:
- generate per-task report
- support export-friendly output format
- aggregate stage metadata, errors, timing, and artifacts

Outputs:
- task report file

### 6.8 WebUI Module
Responsibilities:
- create tasks
- show stage progression
- display subtitle results
- display highlight candidates
- trigger clip export
- expose downloadable artifacts

Important boundary:
- UI interacts with stable task/result contracts only, never directly with model internals

## 7. User Experience / WebUI Information Architecture

The MVP UI is a **single-task workstation** with future expansion room.

### 7.1 Main Screens
1. **New Task**
   - input Bilibili URL
   - choose processing options
   - submit task

2. **Task Detail**
   - show stage-by-stage progress
   - surface logs and failure info
   - central status page

3. **Subtitle + Highlight Workspace**
   - show Chinese transcript/subtitles
   - show bilingual subtitle output
   - show highlight candidates
   - allow candidate confirmation and range adjustment

4. **Export / Results**
   - download subtitle files
   - download clip files
   - download task report

### 7.2 UI Expansion Space Reserved
The information architecture must not block future addition of:
- task history/list pages
- batch job views
- room/channel subscription pages
- more advanced timeline editing
- multiple translation candidates or result comparison views

## 8. Canonical Task Data Flow

One task follows this fixed top-level pipeline:

`Bilibili URL`
→ `task record`
→ `downloaded source video`
→ `normalized audio`
→ `Chinese ASR/timing result`
→ `Chinese-Japanese bilingual subtitle result`
→ `highlight candidate result`
→ `confirmed clip export result`
→ `task report`

This sequence is the core system contract and must remain visible in status reporting.

## 9. Artifact Strategy

Every important stage must persist artifacts to disk.

### Required Artifact Categories
- source video
- source metadata
- media probe metadata
- normalized audio
- Chinese ASR/timing JSON
- Chinese subtitle outputs
- bilingual subtitle JSON
- bilingual subtitle outputs
- highlight candidate JSON
- clip export files
- clip export metadata
- task report
- stage logs

### Why This Is Mandatory
- enables stage-local retries
- supports debugging and auditability
- decouples UI from live in-memory pipeline state
- preserves room for future orchestration changes

## 10. Task-Centric Storage Model

All task artifacts must be organized by `task_id`.

The storage model should support:
- direct lookup of a task’s lifecycle and outputs
- safe deletion or cleanup per task
- future task lists and filtering in the UI
- re-running specific later stages without invalidating prior successful artifacts

## 11. Reliability Model

### 11.1 Stage States
Each stage must expose one of:
- `pending`
- `running`
- `success`
- `failed`
- `skipped`

### 11.2 Retry Policy
Retry should happen **from the failed stage**, not by defaulting to a full restart.

Examples:
- Download succeeded, ASR failed → rerun ASR and downstream stages only
- Translation failed → rerun translation and downstream stages only
- Highlight analysis failed → subtitles remain available while analysis is retried separately

### 11.3 Retryable vs Non-Retryable Failures
Retryable examples:
- transient download failure
- temporary subprocess or I/O problem
- temporary inference/runtime failure

Non-retryable by default:
- invalid user URL
- inaccessible/private source
- missing local model files
- unsupported host environment or misconfiguration

## 12. Logging Model

Two layers are required.

### User-Visible Logs
- short stage summaries
- clear failure reason
- explicit retry suggestion when relevant

### Debug Logs
- subprocess stdout/stderr
- stack traces
- command invocations
- timing details

The WebUI should prefer user-readable failure summaries while still preserving full debug logs for operators.

## 13. Validation Strategy

The MVP verification baseline must cover four classes.

### 13.1 Happy Path
Given one valid Bilibili VOD link, the system must produce:
- downloaded video
- timed Chinese subtitle output
- bilingual Chinese-Japanese subtitle output
- highlight candidates
- at least one exported clip after user confirmation
- task report

### 13.2 Stage Failure
The system must show:
- which stage failed
- why it failed
- whether retry is possible
- successful retry from the failed stage

### 13.3 Invalid Input
An invalid or unusable link must fail early with a clear user-facing explanation.

### 13.4 LAN Access
Another device on the same LAN must be able to access the WebUI and retrieve task results.

## 14. Documentation Deliverables

Two document types are required.

### 14.1 User Manual
Describes:
- purpose and supported workflows
- runtime requirements
- install/startup flow
- WebUI usage
- output interpretation
- common troubleshooting

### 14.2 Task-Level Report
Generated per task and includes:
- source link
- source metadata
- stage timings
- selected models/versions
- outputs produced
- retries/failures
- exported clips

## 15. Git Strategy

Git is a first-class delivery requirement.

### Version-Controlled
- source code
- configuration
- Compose/deployment files
- tests
- docs/specs/manuals

### Excluded from Git
- downloaded media
- normalized audio
- model weights
- task outputs
- caches
- large logs

### Commit Style Expectation
History should remain understandable by feature boundary, such as:
- project skeleton
- downloader integration
- ASR pipeline
- translation pipeline
- highlight pipeline
- export pipeline
- WebUI flow
- docs/manual/reporting

## 16. Future Expansion Preserved by This Design

The MVP architecture intentionally leaves room for:
- batch submission
- task history views
- channel/room subscriptions
- more powerful translation providers
- FunASR substitution or dual-provider mode
- richer highlight scoring
- advanced clip editing UX
- stronger orchestration/runtime separation

## 17. Final Recommendation

Proceed with a Python monolithic workstation using:
- `BBDown` primary / `yt-dlp` fallback for VOD ingestion
- `ffmpeg/ffprobe` for media processing and export
- `WhisperX` for Chinese ASR and timing
- local `Transformers + PyTorch` model for Chinese→Japanese translation
- `PySceneDetect + heuristic scoring` for highlight candidate detection
- `FastAPI` backend
- WebUI over stable task/result APIs
- single NVIDIA GPU host deployment via Docker Compose

This is the best fit for the confirmed goals: mature-component reuse, local-first AI, LAN-friendly operation, Git-traceable development, and an MVP that is useful before it is perfect.
