#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./_dev_common.sh
source "${SCRIPT_DIR}/_dev_common.sh"

CTRANSLATE2_VERSION="4.8.1"
CTRANSLATE2_TAG="v${CTRANSLATE2_VERSION}"
CTRANSLATE2_COMMIT="0d8bcd362ac75ef860ef161d6f0efad0ae439ff0"
CTRANSLATE2_REPOSITORY="https://github.com/OpenNMT/CTranslate2.git"
ROCM_ROOT="${ROCM_PATH:-/opt/rocm}"
HIP_CXX_COMPILER="${ROCM_ROOT}/lib/llvm/bin/clang++"
CTRANSLATE2_CACHE_ROOT="${XDG_CACHE_HOME:-${HOME}/.cache}/nyaru-clipper/ctranslate2-rocm-${CTRANSLATE2_VERSION}"
CTRANSLATE2_SOURCE_DIR="${APP_CTRANSLATE2_SOURCE_ROOT:-${CTRANSLATE2_CACHE_ROOT}/source}"
CTRANSLATE2_BUILD_ROOT="${APP_CTRANSLATE2_BUILD_ROOT:-${CTRANSLATE2_CACHE_ROOT}/builds}"
CTRANSLATE2_INSTALL_PREFIX="${BACKEND_VENV_DIR}/opt/ctranslate2-rocm-${CTRANSLATE2_VERSION}"

usage() {
  printf 'Usage: %s [--dry-run]\n' "$(basename "$0")" >&2
}

print_command() {
  printf '+ '
  printf '%q ' "$@"
  printf '\n'
}

run_command() {
  if ((dry_run)); then
    print_command "$@"
    return
  fi

  "$@"
}

resolve_hip_architecture() {
  if [[ -n "${APP_CTRANSLATE2_HIP_ARCHITECTURE:-}" ]]; then
    printf '%s\n' "${APP_CTRANSLATE2_HIP_ARCHITECTURE}"
    return
  fi

  local hip_architecture
  hip_architecture="$(rocminfo 2>/dev/null | awk '$1 == "Name:" && $2 ~ /^gfx/ { print $2; exit }')"
  if [[ -z "${hip_architecture}" ]]; then
    printf 'unable to detect the AMD GPU architecture with rocminfo; set APP_CTRANSLATE2_HIP_ARCHITECTURE to a gfx target such as gfx1100\n' >&2
    return 1
  fi
  printf '%s\n' "${hip_architecture}"
}

resolve_build_key() {
  local compiler_version
  compiler_version="$("${HIP_CXX_COMPILER}" --version | head -n 1)"
  printf '%s\n' "${BACKEND_VENV_DIR}|${hip_architecture}|${compiler_version}" | sha256sum | cut -c1-16
}

ensure_pinned_source() {
  if [[ ! -d "${CTRANSLATE2_SOURCE_DIR}/.git" ]]; then
    git clone --depth 1 --branch "${CTRANSLATE2_TAG}" --recurse-submodules "${CTRANSLATE2_REPOSITORY}" "${CTRANSLATE2_SOURCE_DIR}"
  fi

  local source_commit
  source_commit="$(git -C "${CTRANSLATE2_SOURCE_DIR}" rev-parse HEAD)"
  if [[ "${source_commit}" != "${CTRANSLATE2_COMMIT}" ]]; then
    printf 'CTranslate2 source cache has commit %s, expected pinned %s. Remove or replace %s before retrying.\n' \
      "${source_commit}" "${CTRANSLATE2_COMMIT}" "${CTRANSLATE2_SOURCE_DIR}" >&2
    return 1
  fi
  if [[ -n "$(git -C "${CTRANSLATE2_SOURCE_DIR}" status --porcelain)" ]]; then
    printf 'CTranslate2 source cache contains local changes: %s. Remove or clean that cache before retrying.\n' "${CTRANSLATE2_SOURCE_DIR}" >&2
    return 1
  fi

  git -C "${CTRANSLATE2_SOURCE_DIR}" submodule sync --recursive
  git -C "${CTRANSLATE2_SOURCE_DIR}" submodule update --init --recursive
}

dry_run=0
while (($# > 0)); do
  case "$1" in
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      usage
      exit 1
      ;;
  esac
done

require_commands cmake git sha256sum uv
enable_wsl_rocm_dxg_detection

if ((dry_run)); then
  hip_architecture="${APP_CTRANSLATE2_HIP_ARCHITECTURE:-<detected-by-rocminfo>}"
  build_key="<backend-venv-gfx-rocm-fingerprint>"
else
  require_commands pkg-config readelf rocminfo
  if [[ ! -x "${HIP_CXX_COMPILER}" ]]; then
    printf 'required ROCm HIP compiler not found: %s\n' "${HIP_CXX_COMPILER}" >&2
    exit 1
  fi
  if ! pkg-config --exists openblas; then
    printf 'OpenBLAS development files are required; install the OpenBLAS development package before retrying.\n' >&2
    exit 1
  fi
  require_backend_python
  hip_architecture="$(resolve_hip_architecture)"
  build_key="$(resolve_build_key)"
fi

CTRANSLATE2_BUILD_DIR="${CTRANSLATE2_BUILD_ROOT}/${build_key}/cmake"
CTRANSLATE2_WHEEL_DIR="${CTRANSLATE2_BUILD_ROOT}/${build_key}/wheel"
CTRANSLATE2_PYTHON_BUILD_DIR="${CTRANSLATE2_BUILD_ROOT}/${build_key}/python-build"
CTRANSLATE2_PYTHON_BDIST_DIR="${CTRANSLATE2_BUILD_ROOT}/${build_key}/python-bdist"

printf 'build CTranslate2 HIP backend: version=%s commit=%s architecture=%s build_key=%s\n' \
  "${CTRANSLATE2_VERSION}" "${CTRANSLATE2_COMMIT}" "${hip_architecture}" "${build_key}"
run_command mkdir -p "$(dirname "${CTRANSLATE2_SOURCE_DIR}")" "${CTRANSLATE2_WHEEL_DIR}"

if ((dry_run)); then
  print_command git clone --depth 1 --branch "${CTRANSLATE2_TAG}" --recurse-submodules "${CTRANSLATE2_REPOSITORY}" "${CTRANSLATE2_SOURCE_DIR}"
  print_command git -C "${CTRANSLATE2_SOURCE_DIR}" rev-parse HEAD
else
  ensure_pinned_source
fi

run_command cmake -S "${CTRANSLATE2_SOURCE_DIR}" -B "${CTRANSLATE2_BUILD_DIR}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${CTRANSLATE2_INSTALL_PREFIX}" \
  -DCMAKE_INSTALL_RPATH="${CTRANSLATE2_INSTALL_PREFIX}/lib;${ROCM_ROOT}/lib;${ROCM_ROOT}/lib/llvm/lib" \
  -DCMAKE_CXX_COMPILER="${HIP_CXX_COMPILER}" \
  -DCMAKE_HIP_COMPILER="${HIP_CXX_COMPILER}" \
  -DCMAKE_PREFIX_PATH="${ROCM_ROOT}" \
  -DWITH_HIP=ON \
  -DWITH_CUDA=OFF \
  -DWITH_MKL=OFF \
  -DWITH_DNNL=OFF \
  -DWITH_OPENBLAS=ON \
  -DOPENMP_RUNTIME=COMP \
  -DWITH_TENSOR_PARALLEL=OFF \
  -DWITH_FLASH_ATTN=OFF \
  -DBUILD_CLI=OFF \
  -DBUILD_TESTS=OFF \
  -DCMAKE_HIP_ARCHITECTURES="${hip_architecture}"
run_command cmake --build "${CTRANSLATE2_BUILD_DIR}" --parallel
run_command cmake --install "${CTRANSLATE2_BUILD_DIR}"
run_command uv pip install --python "${BACKEND_PYTHON_PATH}" pybind11==2.11.1 setuptools wheel

if ((dry_run)); then
  print_command env "CTRANSLATE2_ROOT=${CTRANSLATE2_INSTALL_PREFIX}" "LDFLAGS=-Wl,-rpath,${CTRANSLATE2_INSTALL_PREFIX}/lib -Wl,-rpath,${ROCM_ROOT}/lib -Wl,-rpath,${ROCM_ROOT}/lib/llvm/lib" "${BACKEND_PYTHON_PATH}" setup.py build --build-base "${CTRANSLATE2_PYTHON_BUILD_DIR}" bdist_wheel --bdist-dir "${CTRANSLATE2_PYTHON_BDIST_DIR}" --dist-dir "${CTRANSLATE2_WHEEL_DIR}"
  print_command uv pip install --python "${BACKEND_PYTHON_PATH}" --reinstall --no-deps "${CTRANSLATE2_WHEEL_DIR}/ctranslate2-${CTRANSLATE2_VERSION}-*.whl"
  exit 0
fi

(
  cd "${CTRANSLATE2_SOURCE_DIR}/python"
  CTRANSLATE2_ROOT="${CTRANSLATE2_INSTALL_PREFIX}" \
    LDFLAGS="-Wl,-rpath,${CTRANSLATE2_INSTALL_PREFIX}/lib -Wl,-rpath,${ROCM_ROOT}/lib -Wl,-rpath,${ROCM_ROOT}/lib/llvm/lib" \
    "${BACKEND_PYTHON_PATH}" setup.py build --build-base "${CTRANSLATE2_PYTHON_BUILD_DIR}" bdist_wheel --bdist-dir "${CTRANSLATE2_PYTHON_BDIST_DIR}" --dist-dir "${CTRANSLATE2_WHEEL_DIR}"
)

wheel_path="${CTRANSLATE2_WHEEL_DIR}/ctranslate2-${CTRANSLATE2_VERSION}-cp311-cp311-linux_x86_64.whl"
if [[ ! -f "${wheel_path}" ]]; then
  printf 'CTranslate2 HIP wheel was not created: %s\n' "${wheel_path}" >&2
  exit 1
fi

uv pip install --python "${BACKEND_PYTHON_PATH}" --reinstall --no-deps "${wheel_path}"
LD_LIBRARY_PATH="${CTRANSLATE2_INSTALL_PREFIX}/lib:${ROCM_ROOT}/lib:${ROCM_ROOT}/lib/llvm/lib:${LD_LIBRARY_PATH:-}" \
  "${BACKEND_PYTHON_PATH}" - <<'PY'
import ctranslate2

device_count = ctranslate2.get_cuda_device_count()
print(f"ctranslate2.version={ctranslate2.__version__}")
print(f"ctranslate2.cuda_device_count={device_count}")
print(f"ctranslate2.cuda_compute_types={sorted(ctranslate2.get_supported_compute_types('cuda'))}")
if device_count < 1:
    raise SystemExit("CTranslate2 HIP build cannot see a GPU")
if "float16" not in ctranslate2.get_supported_compute_types("cuda"):
    raise SystemExit("CTranslate2 HIP build does not support the default float16 ASR compute type")
PY

extension_path="$("${BACKEND_PYTHON_PATH}" -c 'import ctranslate2._ext; print(ctranslate2._ext.__file__)')"
if ! readelf -d "${extension_path}" | grep -F "${CTRANSLATE2_INSTALL_PREFIX}/lib" >/dev/null; then
  printf 'CTranslate2 extension is not linked to this backend environment: %s\n' "${extension_path}" >&2
  exit 1
fi
