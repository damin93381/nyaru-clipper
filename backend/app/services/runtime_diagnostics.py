from __future__ import annotations

from collections.abc import Mapping


def _issue(*, code: str, message: str, severity: str = "error") -> dict[str, str]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
    }


def derive_runtime_diagnostics(runtime_profile: Mapping[str, object]) -> tuple[list[dict[str, str]], list[str], bool]:
    platform_payload = runtime_profile.get("platform")
    accelerator_payload = runtime_profile.get("accelerator")
    detected_profile = runtime_profile.get("detected_profile")

    if not isinstance(platform_payload, Mapping) or not isinstance(accelerator_payload, Mapping):
        return [], [], False

    is_wsl = bool(platform_payload.get("is_wsl"))
    torch_available = bool(accelerator_payload.get("torch_available"))
    torch_build_family = accelerator_payload.get("torch_build_family")
    available = bool(accelerator_payload.get("available"))
    device_count = accelerator_payload.get("device_count")
    has_device = isinstance(device_count, int) and device_count > 0

    issues: list[dict[str, str]] = []
    warnings: list[str] = []

    if is_wsl and torch_available and torch_build_family == "cuda":
        issue = _issue(
            code="wrong_torch_build_cuda_on_wsl",
            message="WSL host is using a CUDA-built torch wheel instead of the dedicated ROCm build.",
        )
        issues.append(issue)
        warnings.append("WSL detected a CUDA-built torch wheel. Install the dedicated WSL ROCm backend environment instead.")
    elif is_wsl and torch_available and torch_build_family == "cpu":
        issue = _issue(
            code="cpu_only_torch_on_wsl",
            message="WSL host is using a CPU-only torch build instead of the dedicated ROCm build.",
        )
        issues.append(issue)
        warnings.append("WSL detected a CPU-only torch build. Install the dedicated WSL ROCm backend environment instead.")
    elif torch_available and torch_build_family == "rocm" and (not available or not has_device):
        issue = _issue(
            code="hip_build_no_device",
            message="ROCm torch build is installed, but torch.cuda cannot see a usable GPU device.",
        )
        issues.append(issue)
        warnings.append("WSL detected a ROCm torch build, but no GPU device is available to torch.cuda.")

    if detected_profile == "cpu-only":
        warnings.append("GPU runtime was not detected; backend is operating in cpu-only mode.")

    has_error = any(issue.get("severity") == "error" for issue in issues)
    return issues, warnings, has_error
