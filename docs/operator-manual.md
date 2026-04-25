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

`infra/docker-compose.yml` defines three services:

- `api` runs FastAPI on port `8000`
- `worker` runs the durable single-worker loop from `app.worker`
- `web` runs the Vite dev server on port `5173`

The `api` and `worker` services share the same backend image and the same storage mounts so they see one SQLite database and one artifact tree.

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

From the repo root:

```bash
docker compose -f infra/docker-compose.yml up --build
```

Useful overrides:

- `API_BIND_ADDRESS` to change the API bind IP, default `0.0.0.0`
- `WEB_BIND_ADDRESS` to change the web bind IP, default `0.0.0.0`
- `VITE_API_BASE_URL` to point browser clients at the host API URL
- `APP_BILIBILI_COOKIE_PATH` to point the backend at a cookie file path inside the container

### LAN access caveat for the web UI

The default `VITE_API_BASE_URL` is `http://127.0.0.1:8000/api`.

That works when the browser runs on the same host as Docker. If users open the UI from another LAN device, set `VITE_API_BASE_URL` to the host's LAN address before startup, for example:

```bash
VITE_API_BASE_URL=http://192.168.1.50:8000/api docker compose -f infra/docker-compose.yml up --build
```

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

This MVP assumes one NVIDIA GPU host.

Compose sets:

- `NVIDIA_VISIBLE_DEVICES`
- `NVIDIA_DRIVER_CAPABILITIES`
- GPU reservation entries for `api` and `worker`

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

In the current MVP, pipeline `export` is intentionally marked as skipped until the user confirms a clip through `POST /api/tasks/{task_id}/clips`.

## Logs and troubleshooting

Per-task stage logs live under `/data/tasks/<task_id>/logs/<stage>.log`.

Start here when a run fails:

1. confirm the failing stage from the UI or `/api/tasks/<task_id>/stages`
2. inspect the matching stage log under `/data/tasks/<task_id>/logs`
3. check that model caches are populated and readable
4. verify cookie availability if Bilibili access fails
5. verify the media toolchain resolves inside the backend runtime, for example `docker compose -f infra/docker-compose.yml exec api python -c "import shutil; print({name: shutil.which(name) for name in ('BBDown', 'yt-dlp', 'ffmpeg', 'ffprobe')})"`

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
