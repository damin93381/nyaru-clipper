#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_backend_profile_common.sh
source "${SCRIPT_DIR}/_backend_profile_common.sh"

install_backend_profile "linux-cuda" "${BACKEND_DIR}/requirements-linux-cuda.txt" "$@"
