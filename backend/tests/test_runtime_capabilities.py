from __future__ import annotations

import json
from types import SimpleNamespace


class _FakeCudaRuntime:
    def __init__(self, *, available: bool, device_count: int = 0, device_name: str | None = None):
        self._available = available
        self._device_count = device_count
        self._device_name = device_name

    def is_available(self) -> bool:
        return self._available

    def device_count(self) -> int:
        return self._device_count

    def get_device_name(self, index: int) -> str:
        if self._device_name is None or index >= self._device_count:
            raise RuntimeError("device unavailable")
        return self._device_name


class _FakeTorchModule:
    def __init__(
        self,
        *,
        cuda_available: bool,
        device_count: int = 0,
        device_name: str | None = None,
        cuda_version: str | None = None,
        hip_version: str | None = None,
        version: str = "0.0.0",
    ):
        self.__version__ = version
        self.cuda = _FakeCudaRuntime(
            available=cuda_available,
            device_count=device_count,
            device_name=device_name,
        )
        self.version = SimpleNamespace(cuda=cuda_version, hip=hip_version)


def _patch_platform(
    monkeypatch,
    *,
    system: str = "Linux",
    release: str = "6.8.0-generic",
    version: str = "#1 SMP PREEMPT_DYNAMIC",
    machine: str = "x86_64",
    proc_version: str = "Linux version 6.8.0-generic",
    wsl_distro_name: str | None = None,
) -> None:
    monkeypatch.setattr("app.services.runtime_profile.platform.system", lambda: system)
    monkeypatch.setattr("app.services.runtime_profile.platform.release", lambda: release)
    monkeypatch.setattr("app.services.runtime_profile.platform.version", lambda: version)
    monkeypatch.setattr("app.services.runtime_profile.platform.machine", lambda: machine)
    monkeypatch.setattr("app.services.runtime_profile._read_proc_version", lambda: proc_version)
    if wsl_distro_name is None:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    else:
        monkeypatch.setenv("WSL_DISTRO_NAME", wsl_distro_name)


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


def _patch_all_dependencies_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.capability_checks._which",
        lambda binary: f"/usr/bin/{binary.lower().replace('-', '_')}",
    )

    def _fake_import_module(module_name: str):
        return SimpleNamespace(__version__="1.0.0")

    monkeypatch.setattr("app.services.capability_checks._import_module", _fake_import_module)


def _issue_codes(payload: dict[str, object]) -> list[str]:
    issues = payload.get("issues")
    assert isinstance(issues, list)
    return [issue["code"] for issue in issues]


def test_detect_runtime_profile_classifies_linux_cuda_from_runtime_facts(monkeypatch) -> None:
    from app.services.runtime_profile import detect_runtime_profile

    _patch_platform(monkeypatch)
    monkeypatch.setattr(
        "app.services.runtime_profile._load_torch_module",
        lambda: _FakeTorchModule(
            cuda_available=True,
            device_count=1,
            device_name="NVIDIA GeForce RTX 4080",
            cuda_version="12.4",
            version="2.6.0",
        ),
    )

    payload = detect_runtime_profile()

    assert payload["detected_profile"] == "linux-cuda"
    assert payload["platform"] == {
        "is_wsl": False,
        "machine": "x86_64",
        "release": "6.8.0-generic",
        "system": "linux",
        "version": "#1 SMP PREEMPT_DYNAMIC",
    }
    assert payload["accelerator"] == {
        "available": True,
        "backend": "cuda",
        "cuda_version": "12.4",
        "device_count": 1,
        "device_name": "NVIDIA GeForce RTX 4080",
        "hip_version": None,
        "kind": "cuda",
        "torch_available": True,
        "torch_build_family": "cuda",
        "torch_version": "2.6.0",
    }


def test_detect_runtime_profile_classifies_wsl_rocm_from_runtime_facts(monkeypatch) -> None:
    from app.services.runtime_profile import detect_runtime_profile

    _patch_platform(
        monkeypatch,
        release="6.6.87.2-microsoft-standard-WSL2",
        version="#1 SMP PREEMPT_DYNAMIC Wed Feb 14 00:00:00 UTC 2026",
        proc_version="Linux version 6.6.87.2-microsoft-standard-WSL2",
        wsl_distro_name="Ubuntu-24.04",
    )
    monkeypatch.setattr(
        "app.services.runtime_profile._load_torch_module",
        lambda: _FakeTorchModule(
            cuda_available=True,
            device_count=1,
            device_name="AMD Radeon RX 7800 XT",
            hip_version="6.1.2",
            version="2.6.0+rocm6.1",
        ),
    )

    payload = detect_runtime_profile()

    assert payload["detected_profile"] == "wsl-rocm"
    assert payload["platform"]["is_wsl"] is True
    assert payload["accelerator"] == {
        "available": True,
        "backend": "rocm",
        "cuda_version": None,
        "device_count": 1,
        "device_name": "AMD Radeon RX 7800 XT",
        "hip_version": "6.1.2",
        "kind": "cuda",
        "torch_available": True,
        "torch_build_family": "rocm",
        "torch_version": "2.6.0+rocm6.1",
    }


def test_detect_runtime_profile_classifies_cpu_only_when_gpu_runtime_is_missing(monkeypatch) -> None:
    from app.services.runtime_profile import detect_runtime_profile

    _patch_platform(monkeypatch)
    monkeypatch.setattr(
        "app.services.runtime_profile._load_torch_module",
        lambda: _FakeTorchModule(cuda_available=False, device_count=0, version="2.6.0"),
    )

    payload = detect_runtime_profile()

    assert payload["detected_profile"] == "cpu-only"
    assert payload["accelerator"] == {
        "available": False,
        "backend": "cpu",
        "cuda_version": None,
        "device_count": 0,
        "device_name": None,
        "hip_version": None,
        "kind": "cpu",
        "torch_available": True,
        "torch_build_family": "cpu",
        "torch_version": "2.6.0",
    }


def test_detect_runtime_profile_returns_unknown_when_torch_is_unavailable(monkeypatch) -> None:
    from app.services.runtime_profile import detect_runtime_profile

    _patch_platform(monkeypatch)

    def _raise_missing_torch():
        raise ModuleNotFoundError("No module named 'torch'")

    monkeypatch.setattr("app.services.runtime_profile._load_torch_module", _raise_missing_torch)

    payload = detect_runtime_profile()

    assert payload["detected_profile"] == "unknown"
    assert payload["accelerator"] == {
        "available": False,
        "backend": "unknown",
        "cuda_version": None,
        "device_count": 0,
        "device_name": None,
        "hip_version": None,
        "kind": "unknown",
        "torch_available": False,
        "torch_build_family": "unknown",
        "torch_version": None,
    }


def test_detect_runtime_profile_returns_unknown_when_torch_import_raises_import_error(monkeypatch) -> None:
    from app.services.runtime_profile import detect_runtime_profile

    _patch_platform(monkeypatch)

    def _raise_broken_torch():
        raise ImportError("libtorch_hip.so: undefined symbol")

    monkeypatch.setattr("app.services.runtime_profile._load_torch_module", _raise_broken_torch)

    payload = detect_runtime_profile()

    assert payload["detected_profile"] == "unknown"
    assert payload["accelerator"] == {
        "available": False,
        "backend": "unknown",
        "cuda_version": None,
        "device_count": 0,
        "device_name": None,
        "hip_version": None,
        "kind": "unknown",
        "torch_available": False,
        "torch_build_family": "unknown",
        "torch_version": None,
    }


def test_get_runtime_capabilities_returns_stable_json_serializable_warning_payload(monkeypatch) -> None:
    from app.services.capability_checks import get_runtime_capabilities

    monkeypatch.setattr(
        "app.services.capability_checks.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="cpu-only",
            is_wsl=False,
            available=False,
            backend="cpu",
            device_count=0,
            kind="cpu",
            torch_build_family="cpu",
        ),
    )
    monkeypatch.setattr(
        "app.services.capability_checks._which",
        lambda binary: {
            "ffmpeg": "/usr/bin/ffmpeg",
            "ffprobe": None,
            "yt-dlp": "/usr/bin/yt-dlp",
            "BBDown": None,
        }.get(binary),
    )

    def _fake_import_module(module_name: str):
        available = {
            "torch": SimpleNamespace(__version__="2.6.0"),
            "transformers": SimpleNamespace(__version__="4.52.0"),
            "whisperx": SimpleNamespace(__version__="3.3.1"),
        }
        return available[module_name]

    monkeypatch.setattr("app.services.capability_checks._import_module", _fake_import_module)
    monkeypatch.setattr("app.services.capability_checks._find_module_spec", lambda module_name: None)

    payload = get_runtime_capabilities()

    assert list(payload.keys()) == [
        "status",
        "detected_profile",
        "platform",
        "accelerator",
        "dependencies",
        "warnings",
        "issues",
    ]
    assert list(payload["dependencies"].keys()) == ["tools", "python"]
    assert list(payload["dependencies"]["tools"].keys()) == ["ffmpeg", "ffprobe", "yt-dlp", "BBDown"]
    assert list(payload["dependencies"]["python"].keys()) == [
        "torch",
        "transformers",
        "whisperx",
        "whisperx_diarization",
    ]
    assert payload["status"] == "warning"
    assert payload["issues"] == []
    assert payload["warnings"] == [
        "GPU runtime was not detected; backend is operating in cpu-only mode.",
        "System tool 'ffprobe' was not found on PATH.",
        "System tool 'BBDown' was not found on PATH.",
        "Python dependency path for WhisperX diarization ('pyannote.audio') is unavailable.",
    ]
    assert payload["accelerator"] == {
        "available": False,
        "backend": "cpu",
        "cuda_version": None,
        "device_count": 0,
        "device_name": None,
        "hip_version": None,
        "kind": "cpu",
        "torch_available": True,
        "torch_build_family": "cpu",
        "torch_version": "2.6.0",
    }
    assert payload["dependencies"]["tools"]["ffmpeg"] == {
        "available": True,
        "binary": "ffmpeg",
        "path": "/usr/bin/ffmpeg",
        "status": "ok",
    }
    assert payload["dependencies"]["tools"]["ffprobe"] == {
        "available": False,
        "binary": "ffprobe",
        "path": None,
        "status": "warning",
    }
    assert payload["dependencies"]["python"]["whisperx_diarization"] == {
        "available": False,
        "module": "pyannote.audio",
        "status": "warning",
        "version": None,
    }
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_get_runtime_capabilities_classifies_wsl_cuda_build_mismatch_as_error(monkeypatch) -> None:
    from app.services.capability_checks import get_runtime_capabilities

    monkeypatch.setattr(
        "app.services.capability_checks.detect_runtime_profile",
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
    _patch_all_dependencies_available(monkeypatch)

    payload = get_runtime_capabilities()

    assert payload["status"] == "error"
    assert _issue_codes(payload) == ["wrong_torch_build_cuda_on_wsl"]
    assert payload["warnings"] == [
        "WSL detected a CUDA-built torch wheel. Install the dedicated WSL ROCm backend environment instead.",
        "GPU runtime was not detected; backend is operating in cpu-only mode.",
    ]


def test_get_runtime_capabilities_classifies_wsl_cpu_only_torch_as_error(monkeypatch) -> None:
    from app.services.capability_checks import get_runtime_capabilities

    monkeypatch.setattr(
        "app.services.capability_checks.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="cpu-only",
            is_wsl=True,
            available=False,
            backend="cpu",
            device_count=0,
            kind="cpu",
            torch_build_family="cpu",
        ),
    )
    _patch_all_dependencies_available(monkeypatch)

    payload = get_runtime_capabilities()

    assert payload["status"] == "error"
    assert _issue_codes(payload) == ["cpu_only_torch_on_wsl"]
    assert payload["warnings"] == [
        "WSL detected a CPU-only torch build. Install the dedicated WSL ROCm backend environment instead.",
        "GPU runtime was not detected; backend is operating in cpu-only mode.",
    ]


def test_get_runtime_capabilities_classifies_wsl_hip_build_without_device_as_error(monkeypatch) -> None:
    from app.services.capability_checks import get_runtime_capabilities

    monkeypatch.setattr(
        "app.services.capability_checks.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="cpu-only",
            is_wsl=True,
            available=False,
            backend="cpu",
            device_count=0,
            kind="cpu",
            torch_build_family="rocm",
            hip_version="6.1.2",
            torch_version="2.6.0+rocm6.1",
        ),
    )
    _patch_all_dependencies_available(monkeypatch)

    payload = get_runtime_capabilities()

    assert payload["status"] == "error"
    assert _issue_codes(payload) == ["hip_build_no_device"]
    assert payload["warnings"] == [
        "WSL detected a ROCm torch build, but no GPU device is available to torch.cuda.",
        "GPU runtime was not detected; backend is operating in cpu-only mode.",
    ]


def test_get_runtime_capabilities_keeps_wsl_rocm_happy_path(monkeypatch) -> None:
    from app.services.capability_checks import get_runtime_capabilities

    monkeypatch.setattr(
        "app.services.capability_checks.detect_runtime_profile",
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
            torch_version="2.6.0+rocm6.1",
        ),
    )
    _patch_all_dependencies_available(monkeypatch)

    payload = get_runtime_capabilities()

    assert payload["status"] == "ok"
    assert payload["detected_profile"] == "wsl-rocm"
    assert payload["issues"] == []
    assert payload["warnings"] == []
    assert payload["accelerator"]["torch_build_family"] == "rocm"
    assert payload["accelerator"]["device_name"] == "AMD Radeon RX 7800 XT"


def test_get_runtime_capabilities_keeps_linux_cuda_happy_path(monkeypatch) -> None:
    from app.services.capability_checks import get_runtime_capabilities

    monkeypatch.setattr(
        "app.services.capability_checks.detect_runtime_profile",
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
            torch_version="2.6.0+cu124",
        ),
    )
    _patch_all_dependencies_available(monkeypatch)

    payload = get_runtime_capabilities()

    assert payload["status"] == "ok"
    assert payload["detected_profile"] == "linux-cuda"
    assert payload["issues"] == []
    assert payload["warnings"] == []
    assert payload["accelerator"]["torch_build_family"] == "cuda"
    assert payload["accelerator"]["device_name"] == "NVIDIA GeForce RTX 4080"


def test_get_runtime_capabilities_reports_error_when_core_python_library_is_missing(monkeypatch) -> None:
    from app.services.capability_checks import get_runtime_capabilities

    monkeypatch.setattr(
        "app.services.capability_checks.detect_runtime_profile",
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
        ),
    )
    monkeypatch.setattr(
        "app.services.capability_checks._which",
        lambda binary: f"/usr/bin/{binary.lower().replace('-', '_')}",
    )

    def _fake_import_module(module_name: str):
        if module_name == "whisperx":
            raise ModuleNotFoundError("No module named 'whisperx'")
        return SimpleNamespace(__version__="1.0.0")

    monkeypatch.setattr("app.services.capability_checks._import_module", _fake_import_module)

    payload = get_runtime_capabilities()

    assert payload["status"] == "error"
    assert payload["issues"] == []
    assert payload["warnings"] == ["Python dependency 'whisperx' is not installed."]
    assert payload["dependencies"]["python"]["whisperx"] == {
        "available": False,
        "module": "whisperx",
        "status": "error",
        "version": None,
    }


def test_get_runtime_capabilities_reports_error_when_core_python_library_fails_to_import(monkeypatch) -> None:
    from app.services.capability_checks import get_runtime_capabilities

    monkeypatch.setattr(
        "app.services.capability_checks.detect_runtime_profile",
        lambda: _build_runtime_profile(
            detected_profile="unknown",
            is_wsl=False,
            available=False,
            backend="unknown",
            device_count=0,
            kind="unknown",
            torch_available=False,
            torch_build_family="unknown",
            torch_version=None,
        ),
    )
    monkeypatch.setattr(
        "app.services.capability_checks._which",
        lambda binary: f"/usr/bin/{binary.lower().replace('-', '_')}",
    )

    def _fake_import_module(module_name: str):
        if module_name == "torch":
            raise ImportError("libtorch_hip.so: undefined symbol")
        return SimpleNamespace(__version__="1.0.0")

    monkeypatch.setattr("app.services.capability_checks._import_module", _fake_import_module)

    payload = get_runtime_capabilities()

    assert payload["status"] == "error"
    assert payload["issues"] == []
    assert payload["warnings"] == [
        "Python dependency 'torch' failed to import: libtorch_hip.so: undefined symbol",
    ]
    assert payload["dependencies"]["python"]["torch"] == {
        "available": False,
        "module": "torch",
        "status": "error",
        "version": None,
    }
