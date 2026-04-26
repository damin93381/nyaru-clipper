#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

printf '[release-smoke] defaulting to primary non-docker smoke path via scripts/release_smoke_non_docker.sh\n'
exec "${SCRIPT_DIR}/release_smoke_non_docker.sh" "$@"
