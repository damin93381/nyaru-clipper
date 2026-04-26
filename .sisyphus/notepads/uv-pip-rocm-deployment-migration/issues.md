## 2026-04-25T18:41:02Z Task: session-start
- Current repo is Docker-first at the orchestration layer.
- Current GPU assumptions are CUDA/NVIDIA-biased in settings, docs, worker behavior, and uv.lock.
- Existing smoke script is Docker-first and must be split into primary non-Docker and Docker fallback flows.

## 2026-04-25T19:14:26Z Task: backend-runtime-profile-and-capability-detection
- The current local machine resolves to a warning status in live checks because capability reporting is intentionally non-blocking and reflects missing optional runtime/tool pieces instead of failing import/startup.

## 2026-04-26T04:30:00Z Task: verification-blockers-task-5-task-7
- Task 5 hands-on browser QA is blocked in the current environment because Playwright is installed but no Chrome/Chromium runtime is present, and `playwright install chrome` requires privileged host package installation that cannot complete non-interactively here.
- Task 7 Docker fallback smoke is blocked in this WSL environment because `docker` is not usable from the distro: Docker Desktop WSL integration is disabled or unavailable, so the fallback script exits during compose validation before containers start.
- The host also lacks `dotnet`, which may affect any attempt to install `BBDown` through common Linux/WSL distribution paths.

## 2026-04-26T03:59:48Z Task: deployment-docs-and-indexes
- Markdown files in this repo do not have an LSP server configured, so file-level diagnostics could not run on the touched docs; verification used repo-local grep checks plus a Python content-assertion script instead.

## 2026-04-26T04:18:00Z Task: final-verification-wave-f2-code-quality-review
- The new frontend environment-status shell integration points to `http://127.0.0.1:8000/api` from the Vite dev origin (`http://127.0.0.1:5173`), but the backend does not register CORS middleware and `web/vite.config.ts` does not define a dev proxy. In a real browser this leaves the card dependent on cross-origin access that is not explicitly supported, so live shell integration is not fully verified by the current automated tests.

## 2026-04-26T12:15:00Z Task: final-verification-wave-f3-manual-qa
- Live browser QA against the running uv+pnpm stack shows the shell-level environment status card cannot fetch `http://127.0.0.1:8000/api/runtime/capabilities` from `http://127.0.0.1:5173` because the backend does not return CORS headers; the card falls back to `Unavailable` / `Failed to fetch` in real use even though mocked unit and Playwright smoke coverage pass.

## 2026-04-26T04:54:27Z Task: verification-blockers-update
- Strict Playwright browser QA remains blocked in this environment because installing Chrome requires privileged `sudo` access.
- Docker fallback smoke remains blocked in this WSL distro because Docker Desktop integration is unavailable from the distro.
