# Task 7 report: deterministic OpenAPI export and generated TypeScript contract

## Changed files

- `scripts/export_openapi_schema.py`: exports the FastAPI OpenAPI document through the application entrypoint, recursively sorts JSON object keys, and writes two-space UTF-8 JSON with one trailing newline.
- `web/openapi.json`: checked-in deterministic OpenAPI document.
- `web/src/generated/api-schema.ts`: checked-in `openapi-typescript` contract generated from `web/openapi.json`.
- `web/src/workstation/api/client.ts`: creates the `openapi-fetch` workstation client using the generated `paths` contract.
- `web/src/workstation/api/queryKeys.ts`: exposes stable, typed keys for task summaries, filtered lists, task details, and the queue.
- `web/src/workstation/api/__tests__/client.test.ts`: proves generated list query parameters are serialized and query keys remain stable.
- `web/package.json` and `web/pnpm-lock.yaml`: add pinned OpenAPI tooling and the export/generation commands.
- `backend/tests/test_requirements_export.py`: verifies repeated OpenAPI exports are byte-for-byte identical and include `/api/v2/tasks`.

## Verification

- RED: `../../backend/.venv/bin/python -m pytest backend/tests/test_requirements_export.py::test_openapi_export_is_deterministic_and_contains_workstation_task_contract -q -s` failed because `scripts/export_openapi_schema.py` did not yet exist.
- RED: `PATH=/home/drm/.nvm/versions/node/v22.22.2/bin:$PATH node_modules/.bin/vitest --run src/workstation/api/__tests__/client.test.ts` failed because the new API client module did not yet exist.
- `PATH=/home/drm/.nvm/versions/node/v22.22.2/bin:$PATH node /home/drm/.cache/node/corepack/v1/pnpm/10.33.2/bin/pnpm.cjs --dir web api:generate` — passed.
- Generation drift: staged `web/openapi.json` and `web/src/generated/api-schema.ts`, reran `api:generate`, then `git diff --exit-code -- web/openapi.json web/src/generated/api-schema.ts` — passed.
- `PATH=/home/drm/.nvm/versions/node/v22.22.2/bin:$PATH node /home/drm/.cache/node/corepack/v1/pnpm/10.33.2/bin/pnpm.cjs --dir web test --run src/workstation/api/__tests__/client.test.ts` — `2 passed`.
- `../../backend/.venv/bin/python -m pytest backend/tests/test_requirements_export.py -q -s` — `6 passed`.
- `PATH=/home/drm/.nvm/versions/node/v22.22.2/bin:$PATH node /home/drm/.cache/node/corepack/v1/pnpm/10.33.2/bin/pnpm.cjs --dir web build` — passed (`tsc -b` and Vite production build).
- `git diff --check` — passed.

## Concerns

- The worktree does not contain `backend/.venv`; `api:export` therefore requires an explicit `BACKEND_PYTHON` override when run from this isolated worktree. A normal checkout uses `../backend/.venv/bin/python`.
- Corepack's default pnpm launcher attempted to download pnpm despite the cached `10.33.2` distribution and timed out. Verification used that cached pnpm executable with Node 22; package resolution and lockfile updates completed successfully.

## Review fixes

- Normalized the workstation OpenAPI client base URL to the API origin so both its default and the documented `VITE_API_BASE_URL=http://<host>:8000/api` send generated `/api/v2/...` paths exactly once.
- Removed the worktree-depth fallback from `api:export`. It now defaults to the documented `../backend/.venv/bin/python` and supports an explicit `BACKEND_PYTHON` override for isolated worktrees.
- Added `api:check`, which regenerates the checked-in OpenAPI JSON and TypeScript contract and fails if either artifact drifts. The backend export tests execute this repository-level check.

## Review-fix verification

- `pnpm --dir web api:generate` and `pnpm --dir web api:check` — passed with an explicit isolated-worktree `BACKEND_PYTHON`.
- `./scripts/export_backend_requirements.sh --output <temporary path>` — passed.
- `backend/tests/test_requirements_export.py` — `7 passed`.
- `pnpm --dir web test --run src/workstation/api/__tests__/client.test.ts` — `3 passed`.
- `pnpm --dir web build` — passed.
- `git diff --check` and generated-contract diff check — passed.
- `./scripts/export_backend_requirements.sh --check` remains blocked by a pre-existing stale `backend/requirements.txt`; that generated artifact is outside this review-fix scope and was not changed.
