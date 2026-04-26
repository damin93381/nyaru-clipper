#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_release_smoke_common.sh
source "${SCRIPT_DIR}/_release_smoke_common.sh"

export SMOKE_PATH_LABEL="non-docker"

require_commands setsid uv pnpm python3
setup_api_dev_env
setup_web_dev_env

stack_pid=""
stack_pgid=""

cleanup() {
  local status="$1"

  if [[ -n "${stack_pgid}" ]]; then
    kill -- "-${stack_pgid}" >/dev/null 2>&1 || true
  elif [[ -n "${stack_pid}" ]]; then
    kill "${stack_pid}" >/dev/null 2>&1 || true
  fi

  if [[ -n "${stack_pid}" ]]; then
    wait "${stack_pid}" >/dev/null 2>&1 || true
  fi

  cleanup_smoke_fixture
  exit "${status}"
}

trap 'cleanup $?' EXIT
trap 'exit 130' INT TERM

seed_translation_failure_fixture

smoke_log "starting uv+pnpm local stack via scripts/dev_up.sh..."
setsid "${SCRIPT_DIR}/dev_up.sh" &
stack_pid="$!"
stack_pgid="${stack_pid}"

verify_api_health
verify_web_readiness
verify_host_media_tools
run_downstream_smoke_suite
