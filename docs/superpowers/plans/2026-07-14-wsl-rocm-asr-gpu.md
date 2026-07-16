# WSL ROCm ASR GPU Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` task by task.

**Goal:** Move the existing WhisperX ASR and alignment work from CPU fallback to the local AMD GPU without replacing the workstation pipeline.

**Architecture:** Keep WhisperX/faster-whisper and the existing `device="cuda"` call surface. Replace only the PyPI CTranslate2 wheel in the WSL ROCm installation profile with a reproducible CTranslate2 `v4.8.1` source build configured with `WITH_HIP=ON`; retain CPU fallback when that capability is unavailable. Validate the binary against the existing Bilibili audio before making the installer choose it.

**Tech Stack:** Python 3.11, uv, WhisperX 3.8.5, faster-whisper 1.2.1, CTranslate2 4.8.1, ROCm 7.2/HIP, pytest, Bash.

## Global Constraints

- Preserve the existing single-worker workstation architecture and the `cuda` device token used by ROCm PyTorch.
- Do not alter the running project virtual environment until an isolated HIP build reports a GPU device and transcribes real task audio.
- Keep the normal PyPI CTranslate2 package for non-WSL profiles; the HIP build is WSL ROCm-specific.
- Do not hand-edit generated requirement files; update their generator/source of truth when the dependency contract changes.
- Preserve all pre-existing dirty worktree changes.

---

### Task 1: Prove CTranslate2 HIP on this host

**Files:**
- Create: temporary directory below `/tmp` only; remove it after recording results.
- Read: `backend/app/services/asr_whisperx.py`, `data/tasks/task-c21c228f9633/work/asr-input.wav`.

**Produces:** A pass/fail decision based on an isolated CTranslate2 `v4.8.1` HIP build: `get_cuda_device_count() >= 1`, a successful `WhisperModel(..., device="cuda")` load, and a real transcription that does not fall back to CPU.

- [ ] **Step 1: Build CTranslate2 v4.8.1 outside the project environment**

  Run:

  ```bash
  git clone --depth 1 --branch v4.8.1 https://github.com/OpenNMT/CTranslate2.git /tmp/nyaru-ct2-hip
  cmake -S /tmp/nyaru-ct2-hip -B /tmp/nyaru-ct2-hip/build \
    -DWITH_HIP=ON -DWITH_MKL=OFF -DWITH_DNNL=ON -DCMAKE_BUILD_TYPE=Release
  cmake --build /tmp/nyaru-ct2-hip/build --parallel
  ```

- [ ] **Step 2: Build the matching Python wrapper in an isolated environment**

  Run the CTranslate2 Python wrapper build with `CTRANSLATE2_ROOT=/tmp/nyaru-ct2-hip/install`, then install that wheel together with the already pinned faster-whisper version into an isolated venv.

- [ ] **Step 3: Verify GPU dispatch against the real WAV artifact**

  Run a script with `HSA_ENABLE_DXG_DETECTION=1` that prints the CTranslate2 CUDA device count, model device, compute type, and at least one transcribed segment from `data/tasks/task-c21c228f9633/work/asr-input.wav`.

- [ ] **Step 4: Record the result and clean temporary build artifacts**

  A GPU count of zero, a CPU model device, or a native crash blocks Task 2 and requires an architecture decision before changing the project installer.

### Task 2: Make the WSL installer reproducibly install the HIP backend

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `scripts/_backend_profile_common.sh`
- Modify: `scripts/install_backend_wsl_rocm.sh`
- Modify: `scripts/check_wsl_rocm.sh`
- Test: `backend/tests/test_requirements_export.py`
- Test: `backend/tests/test_runtime_doctor.py`

**Consumes:** Task 1’s exact source revision and successful HIP CMake flags.

**Produces:** A WSL profile install that builds CTranslate2 with HIP after syncing profile dependencies, and a doctor that explicitly reports the CTranslate2 device count and backend status.

- [ ] **Step 1: Write failing installer-contract tests**

  Add deterministic tests asserting that the WSL profile invokes the HIP source-build helper with `WITH_HIP=ON`, while the Linux CUDA profile does not invoke it; add doctor coverage for a visible/non-visible CTranslate2 device.

- [ ] **Step 2: Run the focused tests and confirm they fail**

  Run:

  ```bash
  backend/.venv/bin/python -m pytest -q backend/tests/test_requirements_export.py backend/tests/test_runtime_doctor.py
  ```

- [ ] **Step 3: Implement the smallest profile-specific build helper**

  Add a helper accepting the CTranslate2 tag and ROCm CMake flags, only called by `install_backend_wsl_rocm.sh` after `uv pip sync`; it must support the existing `--dry-run` behavior and avoid mutation during doctor execution.

- [ ] **Step 4: Re-run focused tests and shell syntax checks**

  Run:

  ```bash
  backend/.venv/bin/python -m pytest -q backend/tests/test_requirements_export.py backend/tests/test_runtime_doctor.py
  bash -n scripts/_backend_profile_common.sh scripts/install_backend_wsl_rocm.sh scripts/check_wsl_rocm.sh
  ```

### Task 3: Verify the installed workstation path and document the operational limit

**Files:**
- Modify: `docs/deployment-guide.md`
- Modify: `docs/deployment-guide.zh-CN.md`
- Modify: `docs/operator-manual.md`
- Modify: `docs/operator-manual.zh-CN.md`

**Consumes:** Task 2’s installer and doctor output.

**Produces:** A documented operational path with measurable acceptance checks: no ASR CPU fallback, CTranslate2 GPU count positive, recorded GPU/CPU/RAM/VRAM measurements, and an explicit fallback procedure.

- [ ] **Step 1: Update both language pairs with the WSL HIP installation and rollback instructions**

  State that the normal CTranslate2 wheel is not sufficient for AMD GPU ASR; the supported WSL path is the dedicated installer and doctor.

- [ ] **Step 2: Run the real task audio regression**

  Run the ASR provider with the real `asr-input.wav`, assert its output metadata is `device: "cuda"`, and inspect the worker/task logs for the absence of the CPU fallback warning.

- [ ] **Step 3: Run full focused regression and produce a concise benchmark record**

  Run the ASR, runtime doctor, and dependency-export test suites; record elapsed time, process RSS, and GPU memory/utilization in the task report rather than claiming a speedup without measurement.
