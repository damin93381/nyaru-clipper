from __future__ import annotations

import json
from types import SimpleNamespace


class _FakeCudaRuntime:
    def __init__(self, *, available: bool, device_count: int = 0):
        self._available = available
        self._device_count = device_count

    def is_available(self) -> bool:
        return self._available

    def device_count(self) -> int:
        return self._device_count


class _FakeTorchModule:
    def __init__(
        self,
        *,
        cuda_available: bool,
        device_count: int = 0,
        cuda_version: str | None = None,
        hip_version: str | None = None,
        version: str = "0.0.0",
    ):
        self.__version__ = version
        self.cuda = _FakeCudaRuntime(available=cuda_available, device_count=device_count)
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


def test_detect_runtime_profile_classifies_linux_cuda_from_runtime_facts(monkeypatch) -> None:
    from app.services.runtime_profile import detect_runtime_profile

    _patch_platform(monkeypatch)
    monkeypatch.setattr(
        "app.services.runtime_profile._load_torch_module",
        lambda: _FakeTorchModule(cuda_available=True, device_count=1, cuda_version="12.4", version="2.6.0"),
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
        "hip_version": None,
        "kind": "cuda",
        "torch_available": True,
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
        lambda: _FakeTorchModule(cuda_available=True, device_count=1, hip_version="6.1.2", version="2.6.0+rocm6.1"),
    )

    payload = detect_runtime_profile()

    assert payload["detected_profile"] == "wsl-rocm"
    assert payload["platform"]["is_wsl"] is True
    assert payload["accelerator"]["backend"] == "rocm"
    assert payload["accelerator"]["hip_version"] == "6.1.2"


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
        "hip_version": None,
        "kind": "cpu",
        "torch_available": True,
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
        "hip_version": None,
        "kind": "unknown",
        "torch_available": False,
        "torch_version": None,
    }


def test_get_runtime_capabilities_returns_stable_json_serializable_warning_payload(monkeypatch) -> None:
    from app.services.capability_checks import get_runtime_capabilities

    monkeypatch.setattr(
        "app.services.capability_checks.detect_runtime_profile",
        lambda: {
            "detected_profile": "cpu-only",
            "platform": {
                "is_wsl": False,
                "machine": "x86_64",
                "release": "6.8.0-generic",
                "system": "linux",
                "version": "#1 SMP PREEMPT_DYNAMIC",
            },
            "accelerator": {
                "available": False,
                "backend": "cpu",
                "cuda_version": None,
                "device_count": 0,
                "hip_version": None,
                "kind": "cpu",
                "torch_available": True,
                "torch_version": "2.6.0",
            },
        },
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
        if module_name == "pyannote.audio":
            raise ModuleNotFoundError("No module named 'pyannote.audio'")
        return available[module_name]

    monkeypatch.setattr("app.services.capability_checks._import_module", _fake_import_module)

    payload = get_runtime_capabilities()

    assert list(payload.keys()) == [
        "status",
        "detected_profile",
        "platform",
        "accelerator",
        "dependencies",
        "warnings",
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
    assert payload["warnings"] == [
        "GPU runtime was not detected; backend is operating in cpu-only mode.",
        "System tool 'ffprobe' was not found on PATH.",
        "System tool 'BBDown' was not found on PATH.",
        "Python dependency path for WhisperX diarization ('pyannote.audio') is unavailable.",
    ]
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


def test_get_runtime_capabilities_reports_error_when_core_python_library_is_missing(monkeypatch) -> None:
    from app.services.capability_checks import get_runtime_capabilities

    monkeypatch.setattr(
        "app.services.capability_checks.detect_runtime_profile",
        lambda: {
            "detected_profile": "linux-cuda",
            "platform": {
                "is_wsl": False,
                "machine": "x86_64",
                "release": "6.8.0-generic",
                "system": "linux",
                "version": "#1 SMP PREEMPT_DYNAMIC",
            },
            "accelerator": {
                "available": True,
                "backend": "cuda",
                "cuda_version": "12.4",
                "device_count": 1,
                "hip_version": None,
                "kind": "cuda",
                "torch_available": True,
                "torch_version": "2.6.0",
            },
        },
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
    assert payload["warnings"] == ["Python dependency 'whisperx' is not installed."]
    assert payload["dependencies"]["python"]["whisperx"] == {
        "available": False,
        "module": "whisperx",
        "status": "error",
        "version": None,
    }
