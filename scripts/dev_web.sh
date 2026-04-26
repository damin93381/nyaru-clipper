#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_dev_common.sh
source "${SCRIPT_DIR}/_dev_common.sh"

require_commands pnpm
setup_web_dev_env

exec pnpm --dir "${ROOT_DIR}/web" dev --host "${VITE_HOST}" --port "${VITE_PORT}"
