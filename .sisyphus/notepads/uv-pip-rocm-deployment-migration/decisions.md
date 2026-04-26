## 2026-04-25T18:41:02Z Task: session-start
- Keep backend/ and web/ boundaries; no root workspace refactor.
- Keep gpu_bound schema/field as-is for this migration; behavior changes are observational.
- Use warning-only self-checks; do not block startup.
- Treat requirements.txt as a committed generated artifact.

## 2026-04-25T19:14:26Z Task: backend-runtime-profile-and-capability-detection
- Keep runtime detection as pure backend service functions with no startup/API integration in this task.
- Treat ROCm-on-WSL detection as `is_wsl` + `torch.version.hip` + available accelerator, avoiding config-string inference.

## 2026-04-26T00:00:00Z Task: generated-pip-compatibility-artifact
- Keep `backend/pyproject.toml` and `backend/uv.lock` as the only backend dependency sources; `backend/requirements.txt` is generated exclusively through `scripts/export_backend_requirements.sh`.
- Implement stale detection in the export wrapper itself via `--check` and byte comparison against regenerated output, instead of introducing a second lockfile or hand-maintained requirements workflow.
- Normalize the exported first-party backend package reference to `./backend` so the committed artifact remains installable from the repo root with standard pip usage.

## 2026-04-26T02:40:00Z Task: worker-runtime-warnings
- Keep worker warning surfacing behavioral and observational only: no `gpu_bound` schema changes and no task-blocking behavior.
- Reuse `app.services.capability_checks.get_runtime_capabilities()` directly in the worker and surface only the deterministic subset `{status, detected_profile, warnings}` in the warning line so later API/UI/docs tasks can parse stable output without depending on the full capability payload.

## 2026-04-25T19:45:38Z Task: capability-api-and-startup-status
- Kept startup logging intentionally to one JSON line on logger `app.runtime` with `event`, `profile`, `status`, and `warnings` so deployment logs and tests can target a single structured readiness-adjacent record.

## 2026-04-26T03:59:48Z Task: deployment-docs-and-indexes
- Added standalone English and Chinese deployment guides instead of overloading the operator manuals, so startup and support-matrix guidance stays immediately discoverable from README and docs indexes while operator manuals remain operations-focused.
- Kept Docker sections in every touched doc, but consistently positioned them after the host workflow and labeled them as fallback only to avoid reintroducing Docker-first wording through cross-links or startup examples.
