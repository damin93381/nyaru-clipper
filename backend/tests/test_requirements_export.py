from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "export_backend_requirements.sh"


def _run_export(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(EXPORT_SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_export_script_generates_repo_root_installable_local_package_reference(tmp_path) -> None:
    output_path = tmp_path / "requirements.txt"

    result = _run_export("--output", str(output_path))

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_path.exists()

    lines = output_path.read_text(encoding="utf-8").splitlines()

    assert "./backend" in lines
    assert "." not in lines
    assert "-e ." not in lines


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
