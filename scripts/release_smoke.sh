#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${ROOT_DIR}/.bin:${PATH}"
COMPOSE_FILE="${ROOT_DIR}/infra/docker-compose.yml"
export COMPOSE_PROJECT_NAME="bilibili-vtuber-suite-smoke"

for command_name in docker pnpm uv python3; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    printf 'required command not found: %s\n' "${command_name}" >&2
    exit 1
  fi
done

FIXTURE_DIR="$(mktemp -d)"

cleanup() {
  docker compose -f "${COMPOSE_FILE}" down --remove-orphans >/dev/null 2>&1 || true
  rm -rf "${FIXTURE_DIR}"
}

trap cleanup EXIT

wait_for_url() {
  local label="$1"
  local url="$2"

  LABEL="${label}" URL="${url}" python3 - <<'PY'
import json
import os
import sys
import time
import urllib.error
import urllib.request

label = os.environ["LABEL"]
url = os.environ["URL"]
deadline = time.time() + 180
last_error = "no response"

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = response.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
            print(f"{label} response: {json.dumps(parsed, sort_keys=True)}")
        except json.JSONDecodeError:
            print(f"{label} response: {payload}")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        last_error = str(exc)
        time.sleep(2)

print(f"timed out waiting for {label} at {url}: {last_error}", file=sys.stderr)
sys.exit(1)
PY
}

printf 'seeding deterministic translation-failure fixture...\n'
python3 "${ROOT_DIR}/scripts/seed_failure_fixture.py" \
  "${FIXTURE_DIR}/task-flow-failed123" \
  --task-id "task-flow-failed123" \
  --public-prefix "/fixtures/task-flow-failed123"

printf 'validating compose configuration...\n'
docker compose -f "${COMPOSE_FILE}" config >/dev/null

printf 'starting compose api/worker/web stack...\n'
docker compose -f "${COMPOSE_FILE}" up -d --build api worker web

printf 'waiting for API, worker, and web readiness...\n'
wait_for_url "api health" "http://127.0.0.1:8000/api/health"
wait_for_url "web root" "http://127.0.0.1:5173"

printf 'verifying runtime media tools inside api container...\n'
docker compose -f "${COMPOSE_FILE}" exec -T api python -c "import json, shutil; tools = {name: shutil.which(name) for name in ('BBDown', 'yt-dlp', 'ffmpeg', 'ffprobe')}; print(json.dumps(tools, sort_keys=True)); assert all(tools.values()), tools"

printf 'compose service state...\n'
docker compose -f "${COMPOSE_FILE}" ps

printf 'running backend worker smoke test (no live media tools exercised)...\n'
uv run --project "${ROOT_DIR}/backend" pytest "${ROOT_DIR}/backend/tests/test_e2e_pipeline.py"

printf 'running frontend unit tests...\n'
pnpm --dir "${ROOT_DIR}/web" test -- --run

printf 'building frontend bundle...\n'
pnpm --dir "${ROOT_DIR}/web" build

printf 'running targeted Playwright task flow smoke...\n'
CI="" pnpm --dir "${ROOT_DIR}/web" exec playwright test e2e/task-flow.spec.ts --reporter=line
