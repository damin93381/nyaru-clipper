#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_dev_common.sh"

require_commands uv

uv run --project backend python -m app.runtime_doctor "$@"
