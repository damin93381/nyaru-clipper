#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_dev_common.sh
source "${SCRIPT_DIR}/_dev_common.sh"

require_commands uv pnpm python3
setup_api_dev_env
setup_web_dev_env

children=()

cleanup() {
  local status="$1"

  if ((${#children[@]} > 0)); then
    kill "${children[@]}" >/dev/null 2>&1 || true
    wait "${children[@]}" >/dev/null 2>&1 || true
  fi

  exit "${status}"
}

trap 'cleanup $?' EXIT
trap 'exit 130' INT TERM

printf 'starting local api...\n'
"${SCRIPT_DIR}/dev_api.sh" &
api_pid="$!"
children+=("${api_pid}")

printf 'waiting for api readiness...\n'
wait_for_url "api health" "http://127.0.0.1:${APP_PORT}/api/health"

printf 'starting local worker...\n'
"${SCRIPT_DIR}/dev_worker.sh" &
worker_pid="$!"
children+=("${worker_pid}")

printf 'starting local web...\n'
"${SCRIPT_DIR}/dev_web.sh" &
web_pid="$!"
children+=("${web_pid}")

printf 'waiting for web readiness...\n'
wait_for_url "web root" "http://127.0.0.1:${VITE_PORT}"

printf 'local stack ready: api=http://127.0.0.1:%s web=http://127.0.0.1:%s\n' "${APP_PORT}" "${VITE_PORT}"

wait -n "${api_pid}" "${worker_pid}" "${web_pid}"
