#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_backend_profile_common.sh
source "${SCRIPT_DIR}/_backend_profile_common.sh"

install_backend_profile "wsl-rocm" "${BACKEND_DIR}/requirements-wsl-rocm.txt" "$@"
printf 'ASR backend builder: %s\n' "${SCRIPT_DIR}/build_ctranslate2_wsl_rocm.sh"
"${SCRIPT_DIR}/build_ctranslate2_wsl_rocm.sh" "$@"
