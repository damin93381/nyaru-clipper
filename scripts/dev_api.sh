#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_dev_common.sh
source "${SCRIPT_DIR}/_dev_common.sh"

require_commands uv
setup_api_dev_env

exec uv run --project "${ROOT_DIR}/backend" uvicorn app.main:app --host "${APP_HOST}" --port "${APP_PORT}"
