from __future__ import annotations

import os
from pathlib import Path


def get_data_dir() -> Path:
    configured = os.getenv("APP_DATA_DIR")
    if configured:
        return Path(configured)

    container_data_dir = Path("/data")
    try:
        container_data_dir.mkdir(parents=True, exist_ok=True)
        return container_data_dir
    except PermissionError:
        repo_data_dir = Path(__file__).resolve().parents[2] / "data"
        repo_data_dir.mkdir(parents=True, exist_ok=True)
        return repo_data_dir
