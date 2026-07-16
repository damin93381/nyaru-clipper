#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
BACKEND_VENV_DIR="${BACKEND_DIR}/.venv"
BACKEND_PYTHON_PATH="${BACKEND_VENV_DIR}/bin/python"
export ROOT_DIR
export BACKEND_DIR BACKEND_VENV_DIR BACKEND_PYTHON_PATH
export PATH="${ROOT_DIR}/.bin:${PATH}"
# Required by the ROCm HSA runtime to discover the WSL DXG GPU bridge.
export HSA_ENABLE_DXG_DETECTION=1

require_commands() {
  local command_name
  for command_name in "$@"; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
      printf 'required command not found: %s\n' "${command_name}" >&2
      exit 1
    fi
  done
}

enable_wsl_rocm_dxg_detection() {
  export HSA_ENABLE_DXG_DETECTION=1
}

enable_wsl_huggingface_compatibility() {
  if grep -qiE '(microsoft|wsl)' /proc/sys/kernel/osrelease 2>/dev/null; then
    export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
  fi
}

setup_backend_dev_env() {
  local data_dir="${APP_DATA_DIR:-${ROOT_DIR}/data}"
  local model_cache_root="${APP_MODEL_CACHE_ROOT:-${data_dir}/model-cache}"
  local whisperx_cache_dir="${APP_WHISPERX_MODEL_CACHE_DIR:-${model_cache_root}/whisperx}"
  local hf_home="${HF_HOME:-${model_cache_root}/hf}"

  mkdir -p "${data_dir}" "${model_cache_root}" "${whisperx_cache_dir}" "${hf_home}"

  export APP_DATA_DIR="${data_dir}"
  export APP_WHISPERX_MODEL_CACHE_DIR="${whisperx_cache_dir}"
  export HF_HOME="${hf_home}"
  export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-${hf_home}}"
  enable_wsl_rocm_dxg_detection
  enable_wsl_huggingface_compatibility
}

require_backend_python() {
  if [[ ! -x "${BACKEND_PYTHON_PATH}" ]]; then
    printf 'backend environment is missing: %s\n' "${BACKEND_PYTHON_PATH}" >&2
    printf 'run a dedicated backend installer first, for example:\n' >&2
    printf '  ./scripts/install_backend_linux_cuda.sh\n' >&2
    printf '  ./scripts/install_backend_wsl_rocm.sh\n' >&2
    exit 1
  fi
}

setup_api_dev_env() {
  setup_backend_dev_env
  export APP_HOST="${APP_HOST:-0.0.0.0}"
  export APP_PORT="${APP_PORT:-8000}"
}

setup_web_dev_env() {
  export VITE_HOST="${VITE_HOST:-0.0.0.0}"
  export VITE_PORT="${VITE_PORT:-5173}"
  export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:8000/api}"
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local timeout_seconds="${3:-180}"

  LABEL="${label}" URL="${url}" TIMEOUT_SECONDS="${timeout_seconds}" python3 - <<'PY'
import json
import os
import sys
import time
import urllib.request

label = os.environ["LABEL"]
url = os.environ["URL"]
deadline = time.time() + int(os.environ["TIMEOUT_SECONDS"])
last_error = "no response"

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = response.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
            print(f"{label} response: {json.dumps(parsed, sort_keys=True)}")
        except json.JSONDecodeError:
            print(f"{label} response: {payload}")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        last_error = str(exc)
        time.sleep(2)

print(f"timed out waiting for {label} at {url}: {last_error}", file=sys.stderr)
sys.exit(1)
PY
}
