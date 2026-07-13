from __future__ import annotations

import os
import subprocess
import sys
import tempfile


def test_pytest_uses_a_native_linux_temp_root_when_windows_temp_is_inherited() -> None:
    temp_root = tempfile.gettempdir()
    assert temp_root == "/tmp" or temp_root == "/tmp/nyaru-clipper" or temp_root.startswith("/tmp/nyaru-clipper/")
    assert not temp_root.startswith("/mnt/")


def test_pytest_version_uses_the_same_native_temp_root() -> None:
    environment = os.environ | {
        "TEMP": "/mnt/c/Users/damin/AppData/Local/Temp",
        "TMP": "/mnt/c/Users/damin/AppData/Local/Temp",
    }
    environment.pop("TMPDIR", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr
