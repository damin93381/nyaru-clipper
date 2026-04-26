#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
BACKEND_VENV_DIR="${BACKEND_DIR}/.venv"
BACKEND_PYTHON_PATH="${BACKEND_VENV_DIR}/bin/python"
BASE_REQUIREMENTS_PATH="${BACKEND_DIR}/requirements.txt"
export ROOT_DIR BACKEND_DIR BACKEND_VENV_DIR BACKEND_PYTHON_PATH BASE_REQUIREMENTS_PATH

require_commands() {
  local command_name
  for command_name in "$@"; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
      printf 'required command not found: %s\n' "${command_name}" >&2
      exit 1
    fi
  done
}

backend_profile_usage() {
  local script_name="$1"
  printf 'Usage: %s [--dry-run]\n' "${script_name}" >&2
}

run_or_print() {
  local dry_run="$1"
  shift

  if ((dry_run)); then
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
    return 0
  fi

  "$@"
}

install_backend_profile() {
  local profile_name="$1"
  local profile_requirements_path="$2"
  shift 2

  local dry_run=0
  while (($# > 0)); do
    case "$1" in
      --dry-run)
        dry_run=1
        shift
        ;;
      -h|--help)
        backend_profile_usage "$(basename "$0")"
        return 0
        ;;
      *)
        printf 'unknown argument: %s\n' "$1" >&2
        backend_profile_usage "$(basename "$0")"
        return 1
        ;;
    esac
  done

  require_commands bash uv

  if [[ ! -f "${BASE_REQUIREMENTS_PATH}" ]]; then
    printf 'missing base requirements artifact: %s\n' "${BASE_REQUIREMENTS_PATH}" >&2
    return 1
  fi

  if [[ ! -f "${profile_requirements_path}" ]]; then
    printf 'missing profile requirements artifact: %s\n' "${profile_requirements_path}" >&2
    return 1
  fi

  printf 'install profile: %s\n' "${profile_name}"
  printf 'base artifact: %s\n' "${BASE_REQUIREMENTS_PATH}"
  printf 'profile artifact: %s\n' "${profile_requirements_path}"

  run_or_print "${dry_run}" bash "${ROOT_DIR}/scripts/export_backend_requirements.sh" --check
  run_or_print "${dry_run}" uv venv "${BACKEND_VENV_DIR}"
  run_or_print "${dry_run}" uv pip sync --python "${BACKEND_PYTHON_PATH}" "${BASE_REQUIREMENTS_PATH}" "${profile_requirements_path}"
}
