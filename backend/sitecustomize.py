"""Keep pytest capture files off Windows-mounted temporary directories in WSL."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


if tempfile.gettempdir().startswith("/mnt/"):
    native_temp_root = Path("/tmp/nyaru-clipper")
    native_temp_root.mkdir(exist_ok=True)
    os.environ["TMPDIR"] = str(native_temp_root)
    tempfile.tempdir = str(native_temp_root)
