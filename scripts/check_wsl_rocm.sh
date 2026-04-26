#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_dev_common.sh"

require_commands uv
require_backend_python

"${BACKEND_PYTHON_PATH}" -m app.runtime_doctor "$@"
