# Operator Manual

## Scope

This stack is a trusted-LAN MVP for one GPU host and one active worker.

It is built for:

- one completed Bilibili VOD at a time
- one durable SQLite-backed worker loop
- one trusted operator
- local storage under the repo `data/` tree

It is not designed for public deployment, multi-user access, or internet-facing auth.

## Service layout

The project still exposes the same three runtime roles regardless of whether you use the primary host workflow or the Docker fallback:

- `api` runs FastAPI on port `8000`
- `worker` runs the durable single-worker loop from `app.worker`
- `web` runs the Vite dev server on port `5173`

The primary host workflow starts them with repo scripts. Docker can run the same roles as a fallback.

## Storage and mounts

The current Compose file uses these bind mounts:

- `../data:/data`
- `../data/model-cache:/models`

What lives there:

- `/data/tasks.sqlite3` holds task metadata and queue state
- `/data/tasks/<task_id>/...` holds raw media, work files, reports, exports, and logs
- `/models/whisperx` is the configured WhisperX cache root
- `/models/hf` is the Hugging Face and Transformers cache root

Per-task layout:

- `/data/tasks/<task_id>/raw`
- `/data/tasks/<task_id>/work`
- `/data/tasks/<task_id>/exports`
- `/data/tasks/<task_id>/reports`
- `/data/tasks/<task_id>/logs`

## Startup

Use `uv` plus `pnpm` first. Keep Docker as a fallback.

Read `docs/deployment-guide.md` before first startup. It covers Linux plus CUDA, WSL plus ROCm, the pip compatibility path, runtime capability checks, and Docker fallback details.

### Primary startup

From the repo root:

```bash
./scripts/install_backend_linux_cuda.sh
pnpm --dir web install --frozen-lockfile
./scripts/dev_up.sh
```

Use that dedicated backend install wrapper for the Linux + CUDA host path. It is the supported install contract for the checked-in Linux CUDA dependency profile.

For WSL2 Ubuntu 22.04 or 24.04 with the official AMD ROCm path, install the backend with:

```bash
./scripts/install_backend_wsl_rocm.sh
pnpm --dir web install --frozen-lockfile
./scripts/check_wsl_rocm.sh
./scripts/dev_up.sh
```

Runtime startup stays on the shared `./scripts/dev_api.sh`, `./scripts/dev_worker.sh`, `./scripts/dev_web.sh`, and `./scripts/dev_up.sh` entrypoints.

The WSL installer also compiles the CTranslate2 HIP backend needed by WhisperX ASR. A passing Torch-only check is not sufficient: before accepting ASR capacity, run `./scripts/check_wsl_rocm.sh` and confirm both `ctranslate2.cuda_device_count=1` and support for the configured `APP_WHISPERX_COMPUTE_TYPE` (default `float16`). This is a capability check; validate a real ASR task after changing ROCm, models, or GPU hardware. The first install is a source build and needs `git`, CMake, ROCm development libraries, OpenBLAS headers, and `readelf`.

### Split-process startup

From the repo root:

```bash
./scripts/dev_api.sh
./scripts/dev_worker.sh
./scripts/dev_web.sh
```

### Docker fallback startup

Only use this when the primary host workflow is not practical:

```bash
docker compose -f infra/docker-compose.yml up -d --build api worker web
```

`infra/docker-compose.yml` still defines the same three services for the fallback path.

Useful overrides:

- `APP_HOST` to change the API bind IP, default `0.0.0.0`
- `APP_PORT` to change the API port, default `8000`
- `VITE_HOST` to change the web bind IP, default `0.0.0.0`
- `VITE_PORT` to change the web port, default `5173`
- `VITE_API_BASE_URL` to point browser clients at the host API URL
- `APP_BILIBILI_COOKIE_PATH` to point the backend at a cookie file path
- `APP_DEEPSEEK_API_KEY` for server-side-only subtitle proofreading; never set it in a `VITE_*` variable, browser storage, or a task form
- `APP_DATA_DIR` if you need storage outside the repo `data/` tree
- `APP_EXPORT_VIDEO_BACKEND=windows-amf` to opt confirmed clip export into Windows AMD AMF; the default is `cpu`
- `APP_WINDOWS_FFMPEG_BINARY` to the Windows `ffmpeg.exe` used by AMF, for example `/mnt/e/Program Files/ffmpeg-N-125573-g90436de5e1-win64-gpl-shared/bin/ffmpeg.exe`

When AMF is selected, the exporter converts managed WSL paths for the Windows executable and uses `h264_amf`. A path-conversion, encoder, or output failure is logged and falls back once to CPU `libx264`; artifact metadata records the backend and encoder that actually produced the clip.

### LAN access caveat for the web UI

The default `VITE_API_BASE_URL` is `http://127.0.0.1:8000/api`.

That works when the browser runs on the same host. If users open the UI from another LAN device, set `VITE_API_BASE_URL` to the host's LAN address before startup, for example:

```bash
VITE_API_BASE_URL=http://192.168.1.50:8000/api ./scripts/dev_web.sh
```

For Docker fallback, apply the same value before `docker compose up`.

## Cookie and auth caveats for Bilibili access

The downloader layer supports cookie-based access through `APP_BILIBILI_COOKIE_PATH`.

Important notes:

- Some public VODs may download without cookies.
- Private, member-only, or region-limited VODs can fail without a valid cookie file.
- The backend expects a file path, not a pasted cookie string.
- `BBDown` reads cookie content, while the `yt-dlp` fallback reads the cookie file path. Keep the file readable inside the container.

The current Compose file does not inject a cookie file by default. If you need one, mount it yourself and point `APP_BILIBILI_COOKIE_PATH` at that in-container path.

## Model provisioning expectations

The backend code is local-first.

Current defaults from `backend/app/settings.py`:

- WhisperX model: `large-v3`
- WhisperX device: `cuda`
- WhisperX compute type: `float16`
- translation model: `facebook/nllb-200-distilled-600M`
- translation device: `cuda`

What to expect:

- The first ASR or translation run can populate `/models`.
- Cold-start model downloads can be slow.
- Pre-warming the cache is the safest choice before a real session.
- CPU fallback is not the target operating mode. It may work badly or slowly and should be treated as degraded service.

## GPU assumptions

This MVP assumes one GPU host and one active worker.

Supported host-side runtime targets are:

- Linux + CUDA on a Linux GPU host
- WSL2 Ubuntu 22.04 or 24.04 with the official AMD ROCm path, when the runtime reports `wsl-rocm`

Docker fallback remains NVIDIA-oriented today. `infra/docker-compose.yml` still sets:

- `NVIDIA_VISIBLE_DEVICES`
- `NVIDIA_DRIVER_CAPABILITIES`
- GPU reservation entries for `api` and `worker`

Do not treat Docker fallback as the WSL ROCm path.

The actual pipeline is single-worker by design. Do not scale `worker` horizontally for this MVP.

## Media tooling in the backend image

The shared backend image used by both `api` and `worker` now installs these runtime tools during image build:

- `BBDown`
- `yt-dlp`
- `ffmpeg`
- `ffprobe`

Inside the container, `/app/.bin` is prepended to `PATH` so the backend can keep using the stable default command names from `backend/app/settings.py` while the shims resolve to the installed binaries.

This image change does **not** pre-download WhisperX or translation model weights. Model caches still populate under `/models` on first use or via manual pre-warming.

## Operational flow

The worker picks up one pending durable job at a time.

The canonical backend stage order is:

1. `ingest`
2. `media_prep`
3. `asr`
4. `translation`
5. `highlight`
6. `export`
7. `report`

Automatic highlight filtering is a per-task option for new v2 workstation tasks and defaults to **off**. Enable it in the new-task drawer only when automatic candidate ranking is required. When disabled, the canonical `highlight` stage remains visible but finishes as `skipped`, candidate readiness is reported as `not_applicable`, and the task can still complete successfully. Existing tasks keep automatic highlight filtering enabled after migration so their previous behavior is preserved.

In the current MVP, pipeline `export` is intentionally marked as skipped until the user confirms a clip through `POST /api/tasks/{task_id}/clips`.

### Stage status updates and execution context

Stage status updates have two operating modes:

- normal service or API calls can update a task stage without a worker execution context
- worker-bound pipeline execution validates the current execution token before updating stage state

This boundary lets user-triggered actions such as confirmed clip export and report generation persist their stage results outside the worker loop, while still protecting live worker runs from stale execution tokens after cancellation, force-kill, or stale-job recovery.

## ASR lifecycle visibility and cancellation semantics

During an active `asr` stage, task detail can expose an optional `execution_progress` object.

Operators should treat it as an active-ASR view only:

- it appears only when the backend is tracking a live ASR execution
- it can include the current ASR phase, phase start time, latest heartbeat, and per-phase elapsed timing
- it is cleared again after terminal cleanup, retry from `asr` or earlier, or stale-worker recovery

The phase model is more detailed than the top-level pipeline stage list. While the task stays in stage `asr`, the active child process can report its current ASR phase and timing so operators can distinguish slow progress from a stuck run.

### How to read `cancel_requested` during active ASR

`cancel_requested` is a task-detail overlay status.

What that means in practice:

- task detail can show `cancel_requested` while the active ASR child process is still winding down
- raw stage rows can still show the underlying running `asr` stage during that same window
- this is expected, because the cancellation request has been accepted but the child process has not finished cleanup yet

Use the task-detail status plus `execution_progress` to understand an in-flight ASR cancel. Do not interpret a running `asr` stage row by itself as proof that the cancel request was ignored.

### When `force-kill` is available

`force-kill` is intentionally narrower than ordinary cancel.

It is available only when both of these conditions are true:

- the active job is currently in `asr`
- the backend still has a real tracked process group ID for that ASR child process

If either condition is false, `force-kill` may be absent. Common reasons include:

- the task is no longer in active `asr`
- the child process already exited
- the current run was never associated with a tracked process group
- stale-worker recovery already cleared the control record after making the termination attempt

Absence of `force-kill` does not mean cancellation is unsupported. It means the backend no longer has a safe tracked process group that it can target for an escalation request.

### Scope boundary for this phase

This ASR lifecycle work improves interruption handling and observability only.

It does not change the current quality-preserving defaults for:

- WhisperX model choice
- ASR device selection
- compute type
- translation model selection
- CPU or GPU tuning behavior

Cold starts, model downloads, and degraded CPU fallback behavior remain the same as before. CPU or GPU performance tuning is out of scope for this phase.

## Five-minute ASR, translation, and proofread operation

Media preparation creates exact 300-second task-local WAV slices for new runs. The single worker processes those slices sequentially: ASR first, then translation, then a merged bilingual text-only DeepSeek proofread. It restores segment and word timestamps to the original source timeline; it does not replace or re-encode the source video for subtitle timing.

During a live run, the task overview can expose safe substep summaries from `execution_progress` and the stage summary. `ASR 2/5` and `Translation 4/5` mean completed work slices out of the task total. `Translation merge` means per-slice translations are being assembled, while `Translation proofread` means the final required text review is running. These strings do not expose an API key, provider header, prompt, raw response, cookie, host path, or media payload.

The DeepSeek key is backend-only. Set `APP_DEEPSEEK_API_KEY` in the API/worker process environment or its secret store, and never in the browser, task metadata, frontend file, artifact, or log. The only task-derived data that leave the workstation for proofreading are subtitle text, stable row IDs, and timestamps; source video and audio do not. The fixed server prompt and raw provider response remain backend-only.

### Resume and failure recovery

- A retry reuses valid completed slices. Missing, corrupt, or failed ASR/translation slice outputs are recomputed; completed tasks are not rewritten.
- Retry from `translation` preserves valid ASR output but invalidates old preproofread/final translation publication so stale final subtitles cannot look current.
- `translation_proofread_missing_api_key`: add the backend-only key, restart the API/worker processes that read it, then retry `translation`.
- `translation_proofread_auth_failed` (401): correct the provider credential, then retry `translation`.
- `translation_proofread_billing_failed` (402): resolve provider billing, then retry `translation`.
- `translation_proofread_rate_limit`, `translation_proofread_timeout`, and `translation_proofread_transient_exhausted`: wait for the temporary provider condition to clear, then retry `translation`. Built-in provider retries are bounded.
- `translation_proofread_invalid_response`: retry `translation` after the provider issue is resolved. Reordered rows, changed timestamps, empty text, and malformed responses are rejected.

Proofreading is mandatory for final bilingual publication. A proofread failure does not silently promote preproofread diagnostic subtitles; highlight, report, and export use only validated final bilingual artifacts.

## Runtime capability visibility

Runtime capability checks are non-blocking visibility signals.

Operators should look at four places:

- `./scripts/check_wsl_rocm.sh` for the strict WSL-only doctor result before you trust a WSL host
- `/api/health` for readiness plus the compact `runtime_capabilities` summary
- `/api/runtime/capabilities` for the full payload with `status`, `detected_profile`, `platform`, `accelerator`, `dependencies`, `warnings`, and `issues`
- startup and worker logs for `runtime_capabilities_startup` and `worker_preflight_runtime=<json>`

Warnings do not stop startup. They stay visible in API responses, the UI, and logs so operators can correct degraded environments before running important jobs.

### What the compact summary should tell you

`/api/health` keeps the response compact, but operators should still expect:

- `runtime_capabilities.status`
- `runtime_capabilities.detected_profile`
- `runtime_capabilities.warnings`
- `runtime_capabilities.issue_codes`
- `runtime_capabilities.accelerator`

The compact `accelerator` summary is enough to confirm whether the runtime exposed `torch_build_family`, `available`, `device_count`, and `device_name` without opening the full payload first.

### WSL mismatch codes and what they mean

If the host target is WSL + ROCm, these issue codes are the operator-facing mismatch contract:

- `wrong_torch_build_cuda_on_wsl`: WSL was detected, but the backend environment still contains a CUDA torch build. Reinstall with `./scripts/install_backend_wsl_rocm.sh`, then rerun `./scripts/check_wsl_rocm.sh`.
- `cpu_only_torch_on_wsl`: WSL was detected, but the backend environment contains a CPU-only torch build. Reinstall with `./scripts/install_backend_wsl_rocm.sh`, then rerun `./scripts/check_wsl_rocm.sh`.
- `hip_build_no_device`: ROCm torch is installed, but `torch.cuda` still cannot expose a GPU device. Fix the WSL ROCm stack, then rerun `./scripts/check_wsl_rocm.sh`.

For `hip_build_no_device`, the first operator checks should be:

```bash
rocminfo
ls -l /dev/dxg /dev/kfd
/home/drm/workfile/nyaru-clipper/backend/.venv/bin/python -m torch.utils.collect_env
```

This repository's WSL profile targets the AMD ROCm 7.2 wheel repository. On ROCm releases before 7.13, the shared entrypoints and doctor automatically enable `HSA_ENABLE_DXG_DETECTION=1` when ROCDXG and `/dev/dxg` are present. Export the same variable when launching Python or Uvicorn outside the shared scripts.

One WSL-specific failure mode is that `rocminfo` already sees the AMD GPU, but torch still cannot open it. In that case, apply the AMD-documented HSA runtime replacement inside the dedicated backend environment:

```bash
cp backend/.venv/lib/python3.11/site-packages/torch/lib/libhsa-runtime64.so \
  backend/.venv/lib/python3.11/site-packages/torch/lib/libhsa-runtime64.so.pre-amd-wsl

cp /opt/rocm/lib/libhsa-runtime64.so \
  backend/.venv/lib/python3.11/site-packages/torch/lib/libhsa-runtime64.so
```

Then rerun:

```bash
./scripts/check_wsl_rocm.sh
```

On the host validated for this repository, that replacement moved the doctor result from `hip_build_no_device` to a healthy WSL ROCm state with:

- `detected_profile=wsl-rocm`
- `torch.cuda.is_available=True`
- `torch.cuda.device_count=1`
- `WSL_ROCM_READY`

These codes should line up across API responses, the UI environment status card, the API startup log, and worker preflight logs.

## Logs and troubleshooting

Per-task stage logs live under `/data/tasks/<task_id>/logs/<stage>.log`.

Start here when a run fails:

1. confirm the failing stage from the UI or `/api/tasks/<task_id>/stages`
2. inspect the matching stage log under `/data/tasks/<task_id>/logs`
3. check that model caches are populated and readable
4. verify cookie availability if Bilibili access fails
5. verify the media toolchain resolves in the active runtime

Primary host workflow example:

```bash
python3 -c "import shutil; print({name: shutil.which(name) for name in ('BBDown', 'yt-dlp', 'ffmpeg', 'ffprobe')})"
```

Docker fallback example:

```bash
docker compose -f infra/docker-compose.yml exec api python -c "import shutil; print({name: shutil.which(name) for name in ('BBDown', 'yt-dlp', 'ffmpeg', 'ffprobe')})"
```

## LAN-only and non-support for public deployment

This MVP assumes a trusted LAN.

Do not treat the current stack as internet-ready. It has no:

- auth
- TLS termination
- rate limiting
- reverse-proxy hardening
- secret management layer
- multi-user isolation

Do not expose ports `5173` or `8000` directly to the public internet.
