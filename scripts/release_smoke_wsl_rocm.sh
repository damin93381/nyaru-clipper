#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_release_smoke_common.sh
source "${SCRIPT_DIR}/_release_smoke_common.sh"

export SMOKE_PATH_LABEL="wsl-rocm"

require_commands setsid uv pnpm python3
setup_api_dev_env
setup_web_dev_env

cleanup() {
  local status="$1"

  cleanup_local_dev_stack
  cleanup_smoke_fixture
  exit "${status}"
}

trap 'cleanup $?' EXIT
trap 'exit 130' INT TERM

seed_translation_failure_fixture

smoke_log "running dedicated WSL ROCm doctor via scripts/check_wsl_rocm.sh..."
"${SCRIPT_DIR}/check_wsl_rocm.sh"

start_local_dev_stack
verify_api_health
verify_runtime_profile "wsl-rocm"
verify_web_readiness
verify_host_media_tools
run_downstream_smoke_suite
