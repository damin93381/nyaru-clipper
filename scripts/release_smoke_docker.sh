#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_release_smoke_common.sh
source "${SCRIPT_DIR}/_release_smoke_common.sh"

export SMOKE_PATH_LABEL="docker-fallback"
export COMPOSE_PROJECT_NAME="bilibili-vtuber-suite-smoke"
COMPOSE_FILE="${ROOT_DIR}/infra/docker-compose.yml"

require_commands docker pnpm uv python3
setup_api_dev_env
setup_web_dev_env

cleanup() {
  local status="$1"

  docker compose -f "${COMPOSE_FILE}" down --remove-orphans >/dev/null 2>&1 || true
  cleanup_smoke_fixture
  exit "${status}"
}

trap 'cleanup $?' EXIT
trap 'exit 130' INT TERM

seed_translation_failure_fixture

smoke_log "validating docker compose configuration..."
docker compose -f "${COMPOSE_FILE}" config >/dev/null

smoke_log "starting docker fallback api/worker/web stack..."
docker compose -f "${COMPOSE_FILE}" up -d --build api worker web

verify_api_health
verify_web_readiness
verify_container_media_tools "${COMPOSE_FILE}"

smoke_log "compose service state..."
docker compose -f "${COMPOSE_FILE}" ps

run_downstream_smoke_suite
