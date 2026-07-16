"""Trusted source inspection and local-import catalog boundaries."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.repositories.tasks import normalize_bilibili_source_url
from app.services.downloader import _normalize_metadata
from app.settings import get_settings


_SUPPORTED_MEDIA_EXTENSIONS: Final = frozenset({".mp4", ".mkv", ".mov", ".webm", ".flv"})
_BILIBILI_INSPECTION_TIMEOUT_SECONDS: Final = 30


@dataclass(frozen=True, slots=True)
class SourceCatalogError(Exception):
    """A source request that crosses the configured trust boundary."""

    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class LocalRoot:
    """A configured local media root with an opaque public identity."""

    id: str
    path: Path
    name: str


@dataclass(frozen=True, slots=True)
class LocalEntry:
    """One safely enumerable local directory entry."""

    name: str
    relative_path: str
    kind: str


@dataclass(frozen=True, slots=True)
class LocalDirectoryListing:
    """A root selector and, when selected, its safely enumerable entries."""

    roots: tuple[LocalRoot, ...]
    root_id: str | None
    relative_path: str
    entries: tuple[LocalEntry, ...]


@dataclass(frozen=True, slots=True)
class LocalMediaSource:
    """A supported local media file proven to be within a trusted root."""

    root_id: str
    relative_path: str
    path: Path

    @property
    def locator(self) -> str:
        """Return the opaque local reference that is safe to persist or display."""
        return f"local://{self.root_id}/{self.relative_path}"


@dataclass(frozen=True, slots=True)
class SourceInspection:
    """Normalized Bilibili source metadata suitable for the workstation UI."""

    normalized_url: str
    source_video_id: str
    title: str | None
    uploader: str | None
    duration_seconds: float | None


def list_local_entries(root_id: str, relative_path: str) -> LocalDirectoryListing:
    """List safe children of one configured local-import directory."""
    roots = configured_local_roots()
    root = _root_by_id(roots, root_id)
    directory = _resolve_within_root(root.path, relative_path)
    if not directory.is_dir():
        raise SourceCatalogError("Local catalog path is not a directory")
    entries = tuple(
        sorted(
            (
                entry
                for path in directory.iterdir()
                if (entry := _visible_entry(root.path, path)) is not None
            ),
            key=lambda entry: (entry.name.casefold(), entry.name),
        )
    )
    return LocalDirectoryListing(roots=roots, root_id=root.id, relative_path=_relative_path(root.path, directory), entries=entries)


def list_local_roots() -> LocalDirectoryListing:
    """Expose configured root identities without exposing their host paths."""
    return LocalDirectoryListing(roots=configured_local_roots(), root_id=None, relative_path="", entries=())


def resolve_local_media_source(root_id: str, relative_path: str) -> LocalMediaSource:
    """Resolve a selected local media file and enforce the root containment contract."""
    root = _root_by_id(configured_local_roots(), root_id)
    candidate = _resolve_within_root(root.path, relative_path)
    if not candidate.is_file() or candidate.suffix.casefold() not in _SUPPORTED_MEDIA_EXTENSIONS:
        raise SourceCatalogError("Local source must be a supported media file")
    return LocalMediaSource(root_id=root.id, relative_path=_relative_path(root.path, candidate), path=candidate)


def resolve_persisted_local_media_source(metadata_json: str) -> LocalMediaSource:
    """Re-resolve a task's server-authored local-reference metadata inside configured roots."""
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError as exc:
        raise SourceCatalogError("Local reference metadata is invalid") from exc
    if not isinstance(metadata, dict):
        raise SourceCatalogError("Local reference metadata is invalid")
    root_id = metadata.get("root_id")
    relative_path = metadata.get("relative_path")
    if not isinstance(root_id, str) or not isinstance(relative_path, str):
        raise SourceCatalogError("Local reference metadata is invalid")
    return resolve_local_media_source(root_id, relative_path)


def resolve_local_reference_artifact(metadata_json: str) -> LocalMediaSource | None:
    """Resolve a local-reference artifact only when its server-authored metadata marks it as such."""
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(metadata, dict) or metadata.get("import_mode") != "reference":
        return None
    return resolve_persisted_local_media_source(metadata_json)


def inspect_bilibili_source(url: str) -> SourceInspection:
    """Normalize and inspect one Bilibili URL through the downloader metadata boundary."""
    try:
        normalized_url, source_video_id = normalize_bilibili_source_url(url)
    except ValueError as exc:
        raise SourceCatalogError(str(exc)) from exc
    settings = get_settings()
    try:
        stdout = run_bilibili_inspection_command(
            [settings.ytdlp_binary, "--dump-single-json", "--no-download", normalized_url]
        )
    except SourceCatalogError:
        stdout = run_bilibili_inspection_command(
            [settings.bbdown_binary, "--only-show-info", "--hide-streams", normalized_url]
        )
    metadata = _normalize_metadata(stdout, fallback_video_id=source_video_id)
    title = metadata.get("title")
    uploader = metadata.get("uploader")
    duration = metadata.get("duration_seconds")
    return SourceInspection(
        normalized_url=normalized_url,
        source_video_id=source_video_id,
        title=title if isinstance(title, str) else None,
        uploader=uploader if isinstance(uploader, str) else None,
        duration_seconds=_duration_seconds(duration),
    )


def run_bilibili_inspection_command(command: list[str]) -> str:
    """Run the sole inspection subprocess seam used by the Bilibili inspector."""
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_BILIBILI_INSPECTION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceCatalogError("Bilibili inspection unavailable") from exc
    if completed.returncode != 0:
        raise SourceCatalogError("Bilibili inspection failed")
    return completed.stdout


def configured_local_roots() -> tuple[LocalRoot, ...]:
    """Parse configured absolute roots into stable public identities."""
    configured_values = (value.strip() for value in get_settings().local_import_roots.split(","))
    roots: list[LocalRoot] = []
    seen_paths: set[Path] = set()
    for configured_value in configured_values:
        if not configured_value:
            continue
        configured_path = Path(configured_value)
        if not configured_path.is_absolute():
            raise SourceCatalogError("Configured local import roots must be absolute directories")
        try:
            root_path = configured_path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise SourceCatalogError("Configured local import root does not exist") from exc
        if not root_path.is_dir():
            raise SourceCatalogError("Configured local import root is not a directory")
        if root_path in seen_paths:
            continue
        seen_paths.add(root_path)
        root_id = hashlib.sha256(str(root_path).encode("utf-8")).hexdigest()[:16]
        roots.append(LocalRoot(id=root_id, path=root_path, name=root_path.name or root_path.anchor))
    return tuple(roots)


def _root_by_id(roots: tuple[LocalRoot, ...], root_id: str) -> LocalRoot:
    for root in roots:
        if root.id == root_id:
            return root
    raise SourceCatalogError("Unknown local import root")


def _resolve_within_root(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise SourceCatalogError("Local path must stay within the selected import root")
    try:
        candidate = (root / relative).resolve(strict=True)
    except FileNotFoundError as exc:
        raise SourceCatalogError("Local path does not exist") from exc
    if not candidate.is_relative_to(root):
        raise SourceCatalogError("Local path must stay within the selected import root")
    return candidate


def _visible_entry(root: Path, path: Path) -> LocalEntry | None:
    try:
        candidate = path.resolve(strict=True)
    except FileNotFoundError:
        return None
    if not candidate.is_relative_to(root):
        return None
    relative_path = _relative_path(root, candidate)
    if candidate.is_dir():
        return LocalEntry(name=path.name, relative_path=relative_path, kind="directory")
    if candidate.is_file() and candidate.suffix.casefold() in _SUPPORTED_MEDIA_EXTENSIONS:
        return LocalEntry(name=path.name, relative_path=relative_path, kind="file")
    return None


def _relative_path(root: Path, candidate: Path) -> str:
    relative = candidate.relative_to(root)
    return "" if relative == Path(".") else relative.as_posix()


def _duration_seconds(value: str | int | float | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except ValueError:
        return None
