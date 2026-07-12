from __future__ import annotations

import subprocess

from fastapi.testclient import TestClient
import pytest


def _reset_runtime_state() -> None:
    from app.db import reset_db_runtime

    reset_db_runtime()


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    # Given: an isolated workstation runtime with one explicitly trusted import root.
    database_path = tmp_path / "task-state.sqlite3"
    trusted_root = tmp_path / "trusted-media"
    trusted_root.mkdir()
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("APP_LOCAL_IMPORT_ROOTS", str(trusted_root))
    _reset_runtime_state()

    from app.main import app

    with TestClient(app) as test_client:
        test_client.trusted_root = trusted_root  # type: ignore[attr-defined]
        yield test_client


def test_local_catalog_lists_only_safe_directories_and_supported_media(client: TestClient, tmp_path) -> None:
    # Given: media, a directory, an unsafe outbound symlink, and an unsupported file under the trusted root.
    trusted_root = client.trusted_root  # type: ignore[attr-defined]
    vod_directory = trusted_root / "vod"
    vod_directory.mkdir()
    (trusted_root / "clip.mp4").write_bytes(b"mp4")
    (trusted_root / "archive.mkv").write_bytes(b"mkv")
    (trusted_root / "notes.txt").write_text("ignore", encoding="utf-8")
    outside_file = tmp_path / "outside.mp4"
    outside_file.write_bytes(b"outside")
    (trusted_root / "outside.mp4").symlink_to(outside_file)

    # When: the trusted root and its top-level directory are requested.
    roots_response = client.get("/api/v2/sources/local")
    root_id = roots_response.json()["roots"][0]["id"]
    entries_response = client.get("/api/v2/sources/local", params={"root_id": root_id})

    # Then: only safe directories and supported media are disclosed without host paths.
    assert roots_response.status_code == 200
    assert roots_response.json()["roots"] == [{"id": root_id, "name": "trusted-media"}]
    assert entries_response.status_code == 200
    assert entries_response.json()["root_id"] == root_id
    assert entries_response.json()["relative_path"] == ""
    assert entries_response.json()["entries"] == [
        {"name": "archive.mkv", "relative_path": "archive.mkv", "kind": "file"},
        {"name": "clip.mp4", "relative_path": "clip.mp4", "kind": "file"},
        {"name": "vod", "relative_path": "vod", "kind": "directory"},
    ]


@pytest.mark.parametrize("relative_path", ["../", "/tmp", "outside.mp4"])
def test_local_catalog_rejects_paths_outside_trusted_root(client: TestClient, relative_path: str) -> None:
    # Given: one trusted root and an invalid relative path request.
    root_id = client.get("/api/v2/sources/local").json()["roots"][0]["id"]

    # When: the catalog is asked to traverse outside its configured root.
    response = client.get("/api/v2/sources/local", params={"root_id": root_id, "relative_path": relative_path})

    # Then: the request is rejected at the trust boundary.
    assert response.status_code == 400


def test_bilibili_inspection_normalizes_metadata_without_live_network(client: TestClient, monkeypatch) -> None:
    # Given: the inspection subprocess returns downloader-shaped metadata without a network call.
    monkeypatch.setattr(
        "app.services.source_catalog.run_bilibili_inspection_command",
        lambda command: '{"title":"Nyaru stream","uploader":"Nyaru","duration":42}',
    )

    # When: a Bilibili video URL is inspected.
    response = client.post(
        "/api/v2/sources/bilibili/inspect",
        json={"url": "https://www.bilibili.com/video/BV1abc/?from=search"},
    )

    # Then: normalized, safe source metadata is returned.
    assert response.status_code == 200
    assert response.json() == {
        "normalized_url": "https://www.bilibili.com/video/BV1abc",
        "source_video_id": "BV1abc",
        "title": "Nyaru stream",
        "uploader": "Nyaru",
        "duration_seconds": 42.0,
    }


def test_bilibili_inspection_uses_bounded_subprocess_timeout(client: TestClient, monkeypatch) -> None:
    # Given: a downloader subprocess seam that records its execution limit.
    observed_timeout: float | None = None

    def run(command: list[str], *, check: bool, capture_output: bool, text: bool, timeout: float) -> subprocess.CompletedProcess[str]:
        nonlocal observed_timeout
        observed_timeout = timeout
        return subprocess.CompletedProcess(command, 0, stdout='{"title":"Nyaru stream"}', stderr="")

    monkeypatch.setattr("app.services.source_catalog.subprocess.run", run)

    # When: one Bilibili source is inspected.
    response = client.post(
        "/api/v2/sources/bilibili/inspect",
        json={"url": "https://www.bilibili.com/video/BV1bounded"},
    )

    # Then: the subprocess is bounded and its result remains usable.
    assert response.status_code == 200
    assert observed_timeout is not None
    assert observed_timeout > 0


@pytest.mark.parametrize("error", [OSError("yt-dlp unavailable"), subprocess.TimeoutExpired(["yt-dlp"], 30)])
def test_bilibili_inspection_converts_subprocess_service_failures_to_validation_errors(
    client: TestClient,
    monkeypatch,
    error: OSError | subprocess.TimeoutExpired,
) -> None:
    # Given: the downloader executable is missing or does not finish before its deadline.
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise error

    monkeypatch.setattr("app.services.source_catalog.subprocess.run", run)

    # When: inspection delegates to the downloader subprocess boundary.
    response = client.post(
        "/api/v2/sources/bilibili/inspect",
        json={"url": "https://www.bilibili.com/video/BV1unavailable"},
    )

    # Then: the endpoint returns its intentional validation/service response rather than a 500.
    assert response.status_code == 400
    assert response.json()["detail"] == "Bilibili inspection unavailable"


def test_processing_profiles_expose_only_standard_canonical_pipeline(client: TestClient) -> None:
    # Given: a workstation API client.

    # When: processing profiles are discovered.
    response = client.get("/api/v2/processing-profiles")

    # Then: the first release exposes one non-decorative seven-stage profile.
    assert response.status_code == 200
    assert response.json() == {
        "profiles": [
            {
                "id": "standard",
                "name": "Standard",
                "stages": ["ingest", "media_prep", "asr", "translation", "highlight", "export", "report"],
            }
        ]
    }
