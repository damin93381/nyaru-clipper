#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_dev_common.sh
source "${SCRIPT_DIR}/_dev_common.sh"

smoke_log() {
  printf '[%s] %s\n' "${SMOKE_PATH_LABEL:-smoke}" "$*"
}

stack_pid=""
stack_pgid=""

cleanup_local_dev_stack() {
  if [[ -n "${stack_pgid:-}" ]]; then
    kill -- "-${stack_pgid}" >/dev/null 2>&1 || true
  elif [[ -n "${stack_pid:-}" ]]; then
    kill "${stack_pid}" >/dev/null 2>&1 || true
  fi

  if [[ -n "${stack_pid:-}" ]]; then
    wait "${stack_pid}" >/dev/null 2>&1 || true
  fi

  stack_pid=""
  stack_pgid=""
}

start_local_dev_stack() {
  smoke_log "starting uv+pnpm local stack via scripts/dev_up.sh..."
  setsid "${ROOT_DIR}/scripts/dev_up.sh" &
  stack_pid="$!"
  stack_pgid="${stack_pid}"
}

seed_translation_failure_fixture() {
  local fixture_dir
  fixture_dir="$(mktemp -d)"
  export SMOKE_FIXTURE_DIR="${fixture_dir}"

  smoke_log "seeding deterministic translation-failure fixture..."
  python3 "${ROOT_DIR}/scripts/seed_failure_fixture.py" \
    "${fixture_dir}/task-flow-failed123" \
    --task-id "task-flow-failed123" \
    --public-prefix "/fixtures/task-flow-failed123"
}

cleanup_smoke_fixture() {
  if [[ -n "${SMOKE_FIXTURE_DIR:-}" ]]; then
    rm -rf "${SMOKE_FIXTURE_DIR}"
  fi
}

verify_api_health() {
  smoke_log "waiting for API health readiness..."
  wait_for_url "api health" "http://127.0.0.1:${APP_PORT}/api/health"

  APP_PORT="${APP_PORT}" python3 - <<'PY'
import json
import os
import urllib.request

app_port = os.environ["APP_PORT"]
with urllib.request.urlopen(f"http://127.0.0.1:{app_port}/api/health", timeout=5) as response:
    payload = json.loads(response.read().decode("utf-8"))

assert payload["status"] == "ok", payload
print(f"api health contract: {json.dumps(payload, sort_keys=True)}")
PY
}

verify_runtime_profile() {
  local expected_profile="$1"
  local timeout_seconds="${2:-180}"

  smoke_log "waiting for runtime_capabilities.detected_profile=${expected_profile}..."

  APP_PORT="${APP_PORT}" EXPECTED_PROFILE="${expected_profile}" TIMEOUT_SECONDS="${timeout_seconds}" python3 - <<'PY'
import json
import os
import sys
import time
import urllib.request

app_port = os.environ["APP_PORT"]
expected_profile = os.environ["EXPECTED_PROFILE"]
deadline = time.time() + int(os.environ["TIMEOUT_SECONDS"])
last_error = "no response"

while time.time() < deadline:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{app_port}/api/health", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        runtime_capabilities = payload.get("runtime_capabilities")
        if not isinstance(runtime_capabilities, dict):
            last_error = f"runtime_capabilities missing from payload: {payload!r}"
            time.sleep(2)
            continue

        detected_profile = runtime_capabilities.get("detected_profile")
        if detected_profile == expected_profile:
            print(
                "runtime profile contract: "
                f"{json.dumps(runtime_capabilities, sort_keys=True)}"
            )
            sys.exit(0)

        last_error = (
            "expected runtime_capabilities.detected_profile="
            f"{expected_profile!r}, got {detected_profile!r}"
        )
    except Exception as exc:  # noqa: BLE001
        last_error = str(exc)

    time.sleep(2)

print(
    "timed out waiting for runtime profile readiness at "
    f"http://127.0.0.1:{app_port}/api/health: {last_error}",
    file=sys.stderr,
)
sys.exit(1)
PY
}

verify_web_readiness() {
  smoke_log "waiting for web readiness..."
  wait_for_url "web root" "http://127.0.0.1:${VITE_PORT}"
}

verify_host_media_tools() {
  smoke_log "verifying runtime media tools on host path..."
  python3 - <<'PY'
import json
import shutil

tools = {name: shutil.which(name) for name in ("BBDown", "yt-dlp", "ffmpeg", "ffprobe")}
print(f"host media tools: {json.dumps(tools, sort_keys=True)}")
assert all(tools.values()), tools
PY
}

verify_container_media_tools() {
  local compose_file="$1"
  smoke_log "verifying runtime media tools inside api container..."
  docker compose -f "${compose_file}" exec -T api python -c "import json, shutil; tools = {name: shutil.which(name) for name in ('BBDown', 'yt-dlp', 'ffmpeg', 'ffprobe')}; print(json.dumps(tools, sort_keys=True)); assert all(tools.values()), tools"
}

run_downstream_smoke_suite() {
  smoke_log "running backend worker smoke test (no live media tools exercised)..."
  uv run --project "${ROOT_DIR}/backend" pytest "${ROOT_DIR}/backend/tests/test_e2e_pipeline.py"

  smoke_log "running frontend unit tests..."
  pnpm --dir "${ROOT_DIR}/web" test --run

  smoke_log "building frontend bundle..."
  pnpm --dir "${ROOT_DIR}/web" build

  smoke_log "running targeted Playwright task flow smoke..."
  CI="" pnpm --dir "${ROOT_DIR}/web" exec playwright test e2e/task-flow.spec.ts --reporter=line
}
