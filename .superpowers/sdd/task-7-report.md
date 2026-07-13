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

- The worktree does not contain `backend/.venv`; `api:export` uses that normal repository path first and falls back to the shared venv three levels above the worktree so `api:generate` is directly runnable in this environment. A normal checkout continues to use `../backend/.venv/bin/python`.
- Corepack's default pnpm launcher attempted to download pnpm despite the cached `10.33.2` distribution and timed out. Verification used that cached pnpm executable with Node 22; package resolution and lockfile updates completed successfully.
