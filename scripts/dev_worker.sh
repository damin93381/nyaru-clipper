#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_dev_common.sh
source "${SCRIPT_DIR}/_dev_common.sh"

require_commands uv
setup_backend_dev_env

exec uv run --project "${ROOT_DIR}/backend" python -c "from app.worker import worker_loop; worker_loop()"
