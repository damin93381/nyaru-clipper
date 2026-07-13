from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "export_backend_requirements.sh"
OPENAPI_EXPORT_SCRIPT = REPO_ROOT / "scripts" / "export_openapi_schema.py"
WEB_DIR = REPO_ROOT / "web"
CUDA_PROFILE_PATH = REPO_ROOT / "backend" / "requirements-linux-cuda.txt"
WSL_ROCM_PROFILE_PATH = REPO_ROOT / "backend" / "requirements-wsl-rocm.txt"

ACCELERATOR_PACKAGE_NAMES = {
    "ctranslate2",
    "faster-whisper",
    "torch",
    "torchaudio",
    "torchvision",
    "whisperx",
}
ACCELERATOR_PACKAGE_PREFIXES = ("nvidia-",)
PACKAGE_NAME_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _run_export(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(EXPORT_SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_openapi_export(output_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(OPENAPI_EXPORT_SCRIPT), "--output", str(output_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _read_requirement_entries(path: Path) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and not line.startswith("--")
    ]


def _package_names(lines: list[str]) -> set[str]:
    package_names: set[str] = set()
    for line in lines:
        match = PACKAGE_NAME_PATTERN.match(line)
        if match is None:
            continue
        package_name = match.group(1)
        if package_name.startswith((".", "/")):
            continue
        package_names.add(package_name.lower())
    return package_names


def _package_versions(lines: list[str]) -> dict[str, str]:
    package_versions: dict[str, str] = {}
    for line in lines:
        match = PACKAGE_NAME_PATTERN.match(line)
        if match is None:
            continue
        package_name = match.group(1).lower()
        if package_name.startswith((".", "/")) or "==" not in line:
            continue
        package_versions[package_name] = line.strip()
    return package_versions


def test_export_script_generates_accelerator_neutral_repo_root_installable_requirements(tmp_path) -> None:
    output_path = tmp_path / "requirements.txt"

    result = _run_export("--output", str(output_path))

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_path.exists()

    lines = output_path.read_text(encoding="utf-8").splitlines()
    package_names = _package_names(lines)

    assert "./backend" in lines
    assert "." not in lines
    assert "-e ." not in lines
    assert package_names.isdisjoint(ACCELERATOR_PACKAGE_NAMES)
    assert not any(name.startswith(ACCELERATOR_PACKAGE_PREFIXES) for name in package_names)


def test_export_script_check_detects_stale_requirements_file(tmp_path) -> None:
    output_path = tmp_path / "requirements.txt"

    generate_result = _run_export("--output", str(output_path))
    assert generate_result.returncode == 0, generate_result.stderr or generate_result.stdout

    check_result = _run_export("--check", "--output", str(output_path))
    assert check_result.returncode == 0, check_result.stderr or check_result.stdout

    output_path.write_text(output_path.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    stale_result = _run_export("--check", "--output", str(output_path))

    assert stale_result.returncode == 1
    assert "stale" in (stale_result.stderr or stale_result.stdout).lower()


def test_export_script_prefers_the_backend_virtualenv_python_over_system_python(tmp_path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python3 = fake_bin / "python3"
    fake_python3.write_text("#!/usr/bin/env bash\necho unexpected-system-python >&2\nexit 77\n", encoding="utf-8")
    fake_python3.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    result = subprocess.run(
        [str(EXPORT_SCRIPT), "--check"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_openapi_export_is_deterministic_and_contains_workstation_task_contract(tmp_path) -> None:
    first_output_path = tmp_path / "first-openapi.json"
    second_output_path = tmp_path / "second-openapi.json"

    first_result = _run_openapi_export(first_output_path)
    second_result = _run_openapi_export(second_output_path)

    assert first_result.returncode == 0, first_result.stderr or first_result.stdout
    assert second_result.returncode == 0, second_result.stderr or second_result.stdout
    assert first_output_path.read_bytes() == second_output_path.read_bytes()

    schema = json.loads(first_output_path.read_text(encoding="utf-8"))
    assert "/api/v2/tasks" in schema["paths"]


def test_openapi_declares_queue_conflicts_as_current_queue_snapshots(tmp_path) -> None:
    output_path = tmp_path / "workstation-openapi.json"

    result = _run_openapi_export(output_path)

    assert result.returncode == 0, result.stderr or result.stdout
    schema = json.loads(output_path.read_text(encoding="utf-8"))
    response = schema["paths"]["/api/v2/queue/order"]["put"]["responses"]["409"]
    assert response["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/QueueSnapshotResponse"}


def test_checked_in_workstation_contract_matches_the_backend_openapi_export(tmp_path) -> None:
    output_path = tmp_path / "workstation-openapi.json"

    result = _run_openapi_export(output_path)

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_path.read_bytes() == (WEB_DIR / "openapi.json").read_bytes()


def test_checked_in_linux_cuda_profile_artifact_contains_cuda_runtime_requirements() -> None:
    assert CUDA_PROFILE_PATH.exists(), f"missing profile artifact: {CUDA_PROFILE_PATH}"

    lines = _read_requirement_entries(CUDA_PROFILE_PATH)
    package_names = _package_names(lines)

    assert "torch" in package_names
    assert "whisperx" in package_names
    assert any(name.startswith(ACCELERATOR_PACKAGE_PREFIXES) for name in package_names)
    assert not any("rocm" in line.lower() for line in lines)


def test_checked_in_wsl_rocm_profile_artifact_contains_rocm_torch_without_nvidia_packages() -> None:
    assert WSL_ROCM_PROFILE_PATH.exists(), f"missing profile artifact: {WSL_ROCM_PROFILE_PATH}"

    lines = _read_requirement_entries(WSL_ROCM_PROFILE_PATH)
    package_names = _package_names(lines)

    assert "torch" in package_names
    assert "whisperx" in package_names
    assert any("rocm" in line.lower() for line in lines)
    assert not any(name.startswith(ACCELERATOR_PACKAGE_PREFIXES) for name in package_names)


def test_profile_artifacts_keep_shared_dependency_pins_consistent_with_base_artifact() -> None:
    base_versions = _package_versions(_read_requirement_entries(REPO_ROOT / "backend" / "requirements.txt"))

    for profile_path in (CUDA_PROFILE_PATH, WSL_ROCM_PROFILE_PATH):
        profile_versions = _package_versions(_read_requirement_entries(profile_path))
        conflicting_pins = {
            package_name: (base_versions[package_name], profile_versions[package_name])
            for package_name in sorted(base_versions.keys() & profile_versions.keys())
            if base_versions[package_name] != profile_versions[package_name]
        }

        assert conflicting_pins == {}, (
            f"shared dependencies diverged between {profile_path.name} and requirements.txt: {conflicting_pins}"
        )
