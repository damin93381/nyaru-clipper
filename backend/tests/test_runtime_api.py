import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def _configure_backend_env(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{db_path}")
    _reset_runtime_state()


def test_health_route_preserves_existing_contract_and_adds_runtime_summary(tmp_path, monkeypatch) -> None:
    _configure_backend_env(tmp_path, monkeypatch)
    runtime_summary = {
        "status": "warning",
        "detected_profile": "cpu-only",
        "accelerator": {
            "available": False,
            "backend": "cpu",
            "device_count": 0,
            "device_name": None,
            "torch_build_family": "cpu",
        },
        "warnings": ["GPU runtime was not detected; backend is operating in cpu-only mode."],
        "issue_codes": ["cpu_only_torch_on_wsl"],
    }
    monkeypatch.setattr("app.api.routes.health.get_runtime_capability_summary", lambda: runtime_summary)

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "storage": "ok",
        "database": "ok",
        "runtime_capabilities": runtime_summary,
    }


def test_runtime_capability_summary_includes_compact_issue_codes_and_accelerator_metadata(monkeypatch) -> None:
    capability_payload = {
        "status": "error",
        "detected_profile": "cpu-only",
        "platform": {
            "is_wsl": True,
            "machine": "x86_64",
            "release": "6.8.0-microsoft-standard-WSL2",
            "system": "linux",
            "version": "#1 SMP PREEMPT_DYNAMIC",
        },
        "accelerator": {
            "available": False,
            "backend": "cpu",
            "cuda_version": "12.8",
            "device_count": 0,
            "device_name": None,
            "hip_version": None,
            "kind": "cpu",
            "torch_available": True,
            "torch_build_family": "cuda",
            "torch_version": "2.8.0+cu128",
        },
        "dependencies": {
            "tools": {},
            "python": {},
        },
        "warnings": [
            "WSL detected a CUDA-built torch wheel. Install the dedicated WSL ROCm backend environment instead.",
            "GPU runtime was not detected; backend is operating in cpu-only mode.",
        ],
        "issues": [
            {
                "code": "wrong_torch_build_cuda_on_wsl",
                "message": "WSL host is using a CUDA-built torch wheel instead of the dedicated ROCm build.",
                "severity": "error",
            }
        ],
    }
    monkeypatch.setattr(
        "app.services.runtime_capabilities.get_cached_runtime_capabilities",
        lambda: capability_payload,
    )

    from app.services.runtime_capabilities import get_runtime_capability_summary

    assert get_runtime_capability_summary() == {
        "status": "error",
        "detected_profile": "cpu-only",
        "accelerator": {
            "available": False,
            "backend": "cpu",
            "device_count": 0,
            "device_name": None,
            "torch_build_family": "cuda",
        },
        "warnings": [
            "WSL detected a CUDA-built torch wheel. Install the dedicated WSL ROCm backend environment instead.",
            "GPU runtime was not detected; backend is operating in cpu-only mode.",
        ],
        "issue_codes": ["wrong_torch_build_cuda_on_wsl"],
    }


def test_runtime_capabilities_endpoint_returns_detection_payload_verbatim(tmp_path, monkeypatch) -> None:
    _configure_backend_env(tmp_path, monkeypatch)
    capability_payload = {
        "status": "warning",
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
            "device_name": None,
            "hip_version": None,
            "kind": "cpu",
            "torch_available": True,
            "torch_build_family": "cpu",
            "torch_version": "2.6.0",
        },
        "dependencies": {
            "tools": {
                "ffmpeg": {
                    "available": True,
                    "binary": "ffmpeg",
                    "path": "/usr/bin/ffmpeg",
                    "status": "ok",
                }
            },
            "python": {
                "torch": {
                    "available": True,
                    "module": "torch",
                    "status": "ok",
                    "version": "2.6.0",
                }
            },
        },
        "warnings": ["GPU runtime was not detected; backend is operating in cpu-only mode."],
        "issues": [
            {
                "code": "cpu_only_torch_on_wsl",
                "message": "WSL host is using a CPU-only torch build instead of the dedicated ROCm build.",
                "severity": "error",
            }
        ],
    }
    monkeypatch.setattr(
        "app.api.routes.runtime.get_cached_runtime_capabilities",
        lambda: capability_payload,
    )

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/api/runtime/capabilities")

    assert response.status_code == 200
    assert response.json() == capability_payload


def test_startup_logs_single_structured_capability_summary(tmp_path, monkeypatch, caplog) -> None:
    _configure_backend_env(tmp_path, monkeypatch)
    runtime_summary = {
        "status": "error",
        "detected_profile": "cpu-only",
        "accelerator": {
            "available": False,
            "backend": "cpu",
            "device_count": 0,
            "device_name": None,
            "torch_build_family": "cuda",
        },
        "warnings": [
            "WSL detected a CUDA-built torch wheel. Install the dedicated WSL ROCm backend environment instead.",
            "GPU runtime was not detected; backend is operating in cpu-only mode.",
        ],
        "issue_codes": ["wrong_torch_build_cuda_on_wsl"],
    }
    monkeypatch.setattr("app.main.get_runtime_capability_summary", lambda: runtime_summary)

    from app.main import app

    with caplog.at_level(logging.INFO, logger="app.runtime"):
        with TestClient(app):
            pass

    startup_records = [record for record in caplog.records if record.name == "app.runtime"]

    assert len(startup_records) == 1
    assert json.loads(startup_records[0].getMessage()) == {
        "event": "runtime_capabilities_startup",
        "profile": "cpu-only",
        "status": "error",
        "accelerator": {
            "available": False,
            "backend": "cpu",
            "device_count": 0,
            "device_name": None,
            "torch_build_family": "cuda",
        },
        "warnings": [
            "WSL detected a CUDA-built torch wheel. Install the dedicated WSL ROCm backend environment instead.",
            "GPU runtime was not detected; backend is operating in cpu-only mode.",
        ],
        "issue_codes": ["wrong_torch_build_cuda_on_wsl"],
    }


def test_runtime_capabilities_endpoint_allows_uv_first_browser_origin(tmp_path, monkeypatch) -> None:
    _configure_backend_env(tmp_path, monkeypatch)

    from app.main import app

    with TestClient(app) as client:
        response = client.options(
            "/api/runtime/capabilities",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_runtime_capabilities_endpoint_allows_lan_browser_origin(tmp_path, monkeypatch) -> None:
    _configure_backend_env(tmp_path, monkeypatch)

    from app.main import app

    with TestClient(app) as client:
        response = client.options(
            "/api/runtime/capabilities",
            headers={
                "Origin": "http://172.29.186.118:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://172.29.186.118:5173"
