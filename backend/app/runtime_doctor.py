from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence

from app.services.runtime_diagnostics import derive_runtime_diagnostics
from app.services.runtime_profile import detect_runtime_profile

_REQUIRED_IMPORTS: dict[str, str] = {
    "torch": "torch",
    "transformers": "transformers",
    "whisperx": "whisperx",
}

_REMEDIATION_BY_ISSUE_CODE: dict[str, str] = {
    "wrong_torch_build_cuda_on_wsl": "Install the dedicated WSL ROCm backend environment with ./scripts/install_backend_wsl_rocm.sh.",
    "cpu_only_torch_on_wsl": "Install the dedicated WSL ROCm backend environment with ./scripts/install_backend_wsl_rocm.sh.",
    "hip_build_no_device": "Verify the WSL ROCm stack can expose the AMD GPU to torch.cuda before rerunning this doctor.",
}


def _import_module(module_name: str):
    return importlib.import_module(module_name)


def _import_failure_message(*, module_name: str, error: Exception | None = None) -> str:
    if error is None:
        return f"Required Python dependency '{module_name}' is not installed in the backend environment."
    return f"Required Python dependency '{module_name}' failed to import: {error}"


def _check_runtime_imports() -> tuple[list[str], list[str]]:
    lines: list[str] = []
    failures: list[str] = []

    for label, module_name in _REQUIRED_IMPORTS.items():
        try:
            module = _import_module(module_name)
        except ModuleNotFoundError:
            lines.append(f"import:{label}=missing module={module_name}")
            failures.append(_import_failure_message(module_name=module_name))
            continue
        except Exception as error:
            lines.append(f"import:{label}=failed module={module_name} error={error}")
            failures.append(_import_failure_message(module_name=module_name, error=error))
            continue

        version = getattr(module, "__version__", None)
        lines.append(f"import:{label}=ok version={version or 'unknown'}")

    return lines, failures


def _build_report_lines(runtime_profile: dict[str, object]) -> list[str]:
    platform_payload = runtime_profile["platform"]
    accelerator_payload = runtime_profile["accelerator"]

    return [
        f"platform.is_wsl={platform_payload['is_wsl']}",
        f"detected_profile={runtime_profile['detected_profile']}",
        f"torch.available={accelerator_payload['torch_available']}",
        f"torch.build_family={accelerator_payload['torch_build_family']}",
        f"torch.version={accelerator_payload['torch_version']}",
        f"torch.version.cuda={accelerator_payload['cuda_version']}",
        f"torch.version.hip={accelerator_payload['hip_version']}",
        f"torch.cuda.is_available={accelerator_payload['available']}",
        f"torch.cuda.device_count={accelerator_payload['device_count']}",
    ]


def _device_name_line(runtime_profile: dict[str, object]) -> str | None:
    accelerator_payload = runtime_profile["accelerator"]
    device_count = accelerator_payload.get("device_count")
    if not isinstance(device_count, int) or device_count <= 0:
        return None

    return f"torch.cuda.get_device_name(0)={accelerator_payload.get('device_name')}"


def _doctor_failures(runtime_profile: dict[str, object], *, issues: list[dict[str, str]], import_failures: list[str]) -> list[str]:
    platform_payload = runtime_profile["platform"]
    accelerator_payload = runtime_profile["accelerator"]

    failures: list[str] = []
    if not platform_payload.get("is_wsl"):
        failures.append(
            "Unsupported host: scripts/check_wsl_rocm.sh only supports WSL environments. Use the dedicated WSL ROCm path inside WSL2."
        )

    if not accelerator_payload.get("torch_available"):
        failures.append("torch is not installed in the backend environment. Install the dedicated WSL ROCm backend environment first.")

    for issue in issues:
        code = issue.get("code", "unknown_issue")
        message = issue.get("message", "Unknown runtime issue.")
        remediation = _REMEDIATION_BY_ISSUE_CODE.get(code)
        if remediation:
            failures.append(f"{code}: {message} {remediation}")
        else:
            failures.append(f"{code}: {message}")

    torch_build_family = accelerator_payload.get("torch_build_family")
    if platform_payload.get("is_wsl") and torch_build_family != "rocm":
        failures.append(
            "WSL ROCm doctor requires a ROCm torch build. Install the dedicated WSL ROCm backend environment with ./scripts/install_backend_wsl_rocm.sh."
        )

    if platform_payload.get("is_wsl") and not accelerator_payload.get("hip_version"):
        failures.append("WSL ROCm doctor requires torch.version.hip to be populated by a ROCm torch build.")

    if platform_payload.get("is_wsl") and not accelerator_payload.get("available"):
        failures.append("WSL ROCm doctor requires torch.cuda.is_available() to report True.")

    device_count = accelerator_payload.get("device_count")
    if platform_payload.get("is_wsl") and (not isinstance(device_count, int) or device_count <= 0):
        failures.append("WSL ROCm doctor requires torch.cuda.device_count() to report at least one GPU device.")

    failures.extend(import_failures)
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    del argv

    runtime_profile = detect_runtime_profile()
    issues, _, _ = derive_runtime_diagnostics(runtime_profile)
    import_lines, import_failures = _check_runtime_imports()

    for line in _build_report_lines(runtime_profile):
        print(line)

    device_name_line = _device_name_line(runtime_profile)
    if device_name_line is not None:
        print(device_name_line)

    for line in import_lines:
        print(line)

    failures = _doctor_failures(runtime_profile, issues=issues, import_failures=import_failures)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1

    print("WSL_ROCM_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
