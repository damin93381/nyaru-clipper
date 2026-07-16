from __future__ import annotations

from types import SimpleNamespace


def _build_runtime_profile(
    *,
    detected_profile: str,
    is_wsl: bool,
    available: bool,
    backend: str,
    device_count: int,
    kind: str,
    torch_build_family: str,
    torch_available: bool = True,
    torch_version: str | None = "2.6.0",
    cuda_version: str | None = None,
    hip_version: str | None = None,
    device_name: str | None = None,
) -> dict[str, object]:
    return {
        "detected_profile": detected_profile,
        "platform": {
            "is_wsl": is_wsl,
            "machine": "x86_64",
            "release": "6.8.0-generic",
            "system": "linux",
            "version": "#1 SMP PREEMPT_DYNAMIC",
        },
        "accelerator": {
            "available": available,
            "backend": backend,
            "cuda_version": cuda_version,
            "device_count": device_count,
            "device_name": device_name,
            "hip_version": hip_version,
            "kind": kind,
            "torch_available": torch_available,
            "torch_build_family": torch_build_family,
            "torch_version": torch_version,
        },
    }


def _patch_runtime_imports_available(monkeypatch, *, compute_types: set[str] | None = None) -> None:
    supported_compute_types = compute_types or {"float16", "float32"}

    def _fake_import_module(module_name: str):
        if module_name == "ctranslate2":
            return SimpleNamespace(
                __version__="4.8.1",
                get_cuda_device_count=lambda: 1,
                get_supported_compute_types=lambda device: supported_compute_types,
            )
        return SimpleNamespace(__version__="1.0.0")

    monkeypatch.setattr("app.runtime_doctor._import_module", _fake_import_module)


def _combined_output(capsys) -> str:
    captured = capsys.readouterr()
    return f"{captured.out}\n{captured.err}"


def test_runtime_doctor_fails_outside_wsl(monkeypatch, capsys) -> None:
    from app import runtime_doctor

    monkeypatch.setattr(
        "app.runtime_doctor.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="linux-cuda",
            is_wsl=False,
            available=True,
            backend="cuda",
            device_count=1,
            device_name="NVIDIA GeForce RTX 4080",
            kind="cuda",
            torch_build_family="cuda",
            cuda_version="12.4",
            torch_version="2.8.0+cu128",
        ),
    )
    _patch_runtime_imports_available(monkeypatch)

    exit_code = runtime_doctor.main([])
    output = _combined_output(capsys)

    assert exit_code == 1
    assert "unsupported" in output.lower()
    assert "wsl" in output.lower()
    assert "WSL_ROCM_READY" not in output


def test_runtime_doctor_fails_for_cuda_wheel_on_wsl(monkeypatch, capsys) -> None:
    from app import runtime_doctor

    monkeypatch.setattr(
        "app.runtime_doctor.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="cpu-only",
            is_wsl=True,
            available=False,
            backend="cpu",
            device_count=0,
            kind="cpu",
            torch_build_family="cuda",
            cuda_version="12.8",
            torch_version="2.8.0+cu128",
        ),
    )
    _patch_runtime_imports_available(monkeypatch)

    exit_code = runtime_doctor.main([])
    output = _combined_output(capsys)

    assert exit_code == 1
    assert "wrong_torch_build_cuda_on_wsl" in output
    assert "install_backend_wsl_rocm.sh" in output
    assert "WSL_ROCM_READY" not in output


def test_runtime_doctor_fails_for_cpu_only_torch_on_wsl(monkeypatch, capsys) -> None:
    from app import runtime_doctor

    monkeypatch.setattr(
        "app.runtime_doctor.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="cpu-only",
            is_wsl=True,
            available=False,
            backend="cpu",
            device_count=0,
            kind="cpu",
            torch_build_family="cpu",
            torch_version="2.8.0",
        ),
    )
    _patch_runtime_imports_available(monkeypatch)

    exit_code = runtime_doctor.main([])
    output = _combined_output(capsys)

    assert exit_code == 1
    assert "cpu_only_torch_on_wsl" in output
    assert "install_backend_wsl_rocm.sh" in output
    assert "WSL_ROCM_READY" not in output


def test_runtime_doctor_fails_for_rocm_build_without_visible_device(monkeypatch, capsys) -> None:
    from app import runtime_doctor

    monkeypatch.setattr(
        "app.runtime_doctor.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="cpu-only",
            is_wsl=True,
            available=False,
            backend="cpu",
            device_count=0,
            kind="cpu",
            torch_build_family="rocm",
            hip_version="6.1.2",
            torch_version="2.8.0+rocm6.1",
        ),
    )
    _patch_runtime_imports_available(monkeypatch)

    exit_code = runtime_doctor.main([])
    output = _combined_output(capsys)

    assert exit_code == 1
    assert "hip_build_no_device" in output
    assert "torch.cuda.is_available=False" in output
    assert "WSL_ROCM_READY" not in output


def test_runtime_doctor_reports_ready_for_healthy_wsl_rocm(monkeypatch, capsys) -> None:
    from app import runtime_doctor

    monkeypatch.setattr(
        "app.runtime_doctor.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="wsl-rocm",
            is_wsl=True,
            available=True,
            backend="rocm",
            device_count=1,
            device_name="AMD Radeon RX 7800 XT",
            kind="cuda",
            torch_build_family="rocm",
            hip_version="6.1.2",
            torch_version="2.8.0+rocm6.1",
        ),
    )
    _patch_runtime_imports_available(monkeypatch)

    exit_code = runtime_doctor.main([])
    output = _combined_output(capsys)

    assert exit_code == 0
    assert "WSL_ROCM_READY" in output
    assert "torch.version.hip=6.1.2" in output
    assert "torch.cuda.device_count=1" in output
    assert "torch.cuda.get_device_name(0)=AMD Radeon RX 7800 XT" in output
    assert "ctranslate2.cuda_device_count=1" in output
    assert "ctranslate2.cuda_compute_types=['float16', 'float32']" in output


def test_runtime_doctor_rejects_missing_configured_asr_compute_type(monkeypatch, capsys) -> None:
    from app import runtime_doctor

    monkeypatch.setenv("APP_WHISPERX_COMPUTE_TYPE", "float16")
    monkeypatch.setattr(
        "app.runtime_doctor.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="wsl-rocm",
            is_wsl=True,
            available=True,
            backend="rocm",
            device_count=1,
            device_name="AMD Radeon RX 7800 XT",
            kind="cuda",
            torch_build_family="rocm",
            hip_version="6.1.2",
            torch_version="2.8.0+rocm6.1",
        ),
    )
    _patch_runtime_imports_available(monkeypatch, compute_types={"float32"})

    exit_code = runtime_doctor.main([])
    output = _combined_output(capsys)

    assert exit_code == 1
    assert "configured ASR compute type 'float16'" in output
    assert "WSL_ROCM_READY" not in output


def test_runtime_doctor_reports_ctranslate2_api_failures_without_traceback(monkeypatch, capsys) -> None:
    from app import runtime_doctor

    monkeypatch.setattr(
        "app.runtime_doctor.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="wsl-rocm",
            is_wsl=True,
            available=True,
            backend="rocm",
            device_count=1,
            device_name="AMD Radeon RX 7800 XT",
            kind="cuda",
            torch_build_family="rocm",
            hip_version="6.1.2",
            torch_version="2.8.0+rocm6.1",
        ),
    )

    def _fake_import_module(module_name: str):
        if module_name == "ctranslate2":
            return SimpleNamespace(
                __version__="4.8.1",
                get_cuda_device_count=lambda: 1,
                get_supported_compute_types=lambda device: (_ for _ in ()).throw(AttributeError("missing GPU API")),
            )
        return SimpleNamespace(__version__="1.0.0")

    monkeypatch.setattr("app.runtime_doctor._import_module", _fake_import_module)

    exit_code = runtime_doctor.main([])
    output = _combined_output(capsys)

    assert exit_code == 1
    assert "ctranslate2=failed error=missing GPU API" in output
    assert "WSL_ROCM_READY" not in output


def test_runtime_doctor_reports_import_failures_without_crashing(monkeypatch, capsys) -> None:
    from app import runtime_doctor

    monkeypatch.setattr(
        "app.runtime_doctor.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="unknown",
            is_wsl=True,
            available=False,
            backend="unknown",
            device_count=0,
            kind="unknown",
            torch_available=False,
            torch_build_family="unknown",
            torch_version=None,
        ),
    )

    def _fake_import_module(module_name: str):
        if module_name == "torch":
            raise ImportError("libtorch_hip.so: undefined symbol")
        if module_name == "ctranslate2":
            return SimpleNamespace(
                __version__="4.8.1",
                get_cuda_device_count=lambda: 1,
                get_supported_compute_types=lambda device: {"float16", "float32"},
            )
        return SimpleNamespace(__version__="1.0.0")

    monkeypatch.setattr("app.runtime_doctor._import_module", _fake_import_module)

    exit_code = runtime_doctor.main([])
    output = _combined_output(capsys)

    assert exit_code == 1
    assert "Required Python dependency 'torch' failed to import: libtorch_hip.so: undefined symbol" in output
    assert "WSL_ROCM_READY" not in output
