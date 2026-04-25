from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.repositories.tasks import get_task_record
from app.services.pipeline_support import append_stage_log, run_logged_command, set_stage_status
from app.services.storage import ensure_task_dirs, log_file_for_stage, persist_artifact_metadata
from app.settings import get_settings


@dataclass(slots=True)
class DownloadResult:
    source_metadata: dict[str, Any]
    output_path: Path
    selected_downloader: str
    fallback_used: bool
    auth_cookie_present: bool


class DownloaderFailure(RuntimeError):
    def __init__(self, *, code: str, message: str):
        super().__init__(message)
        self.code = code


def download_bilibili_vod(session: Session, task_id: str) -> DownloadResult:
    record = get_task_record(session, task_id)
    if record is None:
        raise ValueError(f"Unknown task_id: {task_id}")

    task_dirs = ensure_task_dirs(task_id)
    raw_dir = task_dirs["raw"]
    log_path = log_file_for_stage(task_id, "ingest")
    settings = get_settings()
    cookie_value, cookie_present = _load_cookie_value(settings.bilibili_cookie_path)

    append_stage_log(log_path, f"cookie_auth_present={str(cookie_present).lower()}")

    bbdown_path = raw_dir / "source.mp4"
    bbdown_args = _build_bbdown_args(
        settings.bbdown_binary,
        record.task.normalized_source_url,
        raw_dir=raw_dir,
        cookie_value=cookie_value,
    )
    bbdown_result = run_logged_command(bbdown_args, log_path=log_path)
    if bbdown_result.returncode == 0:
        metadata = _normalize_metadata(bbdown_result.stdout, fallback_video_id=record.task.source_video_id)
        output_path = _resolve_output_path(raw_dir, preferred=bbdown_path)
        return _persist_success(
            session,
            task_id=task_id,
            output_path=output_path,
            source_metadata=metadata,
            selected_downloader="bbdown",
            fallback_used=False,
            auth_cookie_present=cookie_present,
        )

    failure = _classify_failure(
        stderr=bbdown_result.stderr,
        stdout=bbdown_result.stdout,
        auth_cookie_present=cookie_present,
    )
    if failure is not None:
        append_stage_log(log_path, f"classified_failure={failure.code}")
        set_stage_status(session, task_id=task_id, stage_name="ingest", status="failed", summary=failure.code)
        session.commit()
        raise failure

    append_stage_log(log_path, "bbdown_failed_falling_back_to_yt_dlp")
    ytdlp_path = raw_dir / "source.mp4"
    ytdlp_args = _build_ytdlp_args(
        settings.ytdlp_binary,
        record.task.normalized_source_url,
        output_path=ytdlp_path,
        cookie_path=settings.bilibili_cookie_path if cookie_present else None,
    )
    ytdlp_result = run_logged_command(ytdlp_args, log_path=log_path)
    if ytdlp_result.returncode != 0:
        fallback_failure = _classify_failure(
            stderr=ytdlp_result.stderr,
            stdout=ytdlp_result.stdout,
            auth_cookie_present=cookie_present,
        ) or DownloaderFailure(code="download_failed", message=ytdlp_result.stderr or "yt-dlp failed")
        append_stage_log(log_path, f"classified_failure={fallback_failure.code}")
        set_stage_status(session, task_id=task_id, stage_name="ingest", status="failed", summary=fallback_failure.code)
        session.commit()
        raise fallback_failure

    metadata = _normalize_metadata(ytdlp_result.stdout, fallback_video_id=record.task.source_video_id)
    output_path = _resolve_output_path(raw_dir, preferred=ytdlp_path)
    return _persist_success(
        session,
        task_id=task_id,
        output_path=output_path,
        source_metadata=metadata,
        selected_downloader="yt-dlp",
        fallback_used=True,
        auth_cookie_present=cookie_present,
    )


def _load_cookie_value(cookie_path: Path | None) -> tuple[str | None, bool]:
    if cookie_path is None:
        return None, False
    if not cookie_path.exists() or not cookie_path.is_file():
        return None, False
    value = cookie_path.read_text(encoding="utf-8").strip()
    return (value or None), bool(value)


def _build_bbdown_args(binary: str, source_url: str, *, raw_dir: Path, cookie_value: str | None) -> list[str]:
    args = [binary, "--work-dir", str(raw_dir), "--file-pattern", "source"]
    if cookie_value:
        args.extend(["-c", cookie_value])
    args.append(source_url)
    return args


def _build_ytdlp_args(binary: str, source_url: str, *, output_path: Path, cookie_path: Path | None) -> list[str]:
    args = [
        binary,
        "--print-json",
        "--output",
        str(output_path),
    ]
    if cookie_path is not None:
        args.extend(["--cookies", str(cookie_path)])
    args.append(source_url)
    return args


def _resolve_output_path(raw_dir: Path, *, preferred: Path) -> Path:
    if preferred.exists():
        return preferred
    matches = sorted(path for path in raw_dir.glob("source.*") if path.is_file() and path.name != "source-metadata.json")
    if matches:
        return matches[0]
    raise DownloaderFailure(code="download_failed", message="Downloader did not create an output file")


def _normalize_metadata(stdout: str, *, fallback_video_id: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = {}
        for line in stdout.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            parsed[key.strip().lower()] = value.strip()
    if isinstance(parsed, dict):
        payload["title"] = parsed.get("title") or parsed.get("videoTitle") or parsed.get("video_title")
        payload["uploader"] = parsed.get("uploader") or parsed.get("ownerName") or parsed.get("owner_name")
        payload["duration_seconds"] = parsed.get("duration_seconds") or parsed.get("duration")
        payload["source_video_id"] = parsed.get("source_video_id") or parsed.get("id") or parsed.get("bvid") or fallback_video_id
    normalized = {key: value for key, value in payload.items() if value is not None}
    if fallback_video_id and "source_video_id" not in normalized:
        normalized["source_video_id"] = fallback_video_id
    return normalized


def _classify_failure(*, stderr: str, stdout: str, auth_cookie_present: bool) -> DownloaderFailure | None:
    combined = f"{stderr}\n{stdout}".lower()
    if any(marker in combined for marker in ["private", "region", "geo", "会员专享", "area limit"]):
        return DownloaderFailure(code="private_or_region_locked", message=stderr or stdout or "Access restricted")
    if any(marker in combined for marker in ["login required", "cookie", "sign in", "登录"]):
        code = "auth_missing" if not auth_cookie_present else "auth_required"
        return DownloaderFailure(code=code, message=stderr or stdout or "Authentication required")
    return None


def _persist_success(
    session: Session,
    *,
    task_id: str,
    output_path: Path,
    source_metadata: dict[str, Any],
    selected_downloader: str,
    fallback_used: bool,
    auth_cookie_present: bool,
) -> DownloadResult:
    metadata_path = output_path.parent / "source-metadata.json"
    normalized_contract = {
        "auth_cookie_present": auth_cookie_present,
        "fallback_used": fallback_used,
        "output_file_path": str(output_path),
        "selected_downloader": selected_downloader,
        "source_metadata": source_metadata,
    }
    metadata_path.write_text(json.dumps(source_metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="ingest",
        kind="source_video",
        path=output_path,
        metadata=normalized_contract,
    )
    persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="ingest",
        kind="source_metadata",
        path=metadata_path,
        metadata={"source_metadata": source_metadata},
    )
    summary = f"Downloaded source video via {selected_downloader}"
    if fallback_used:
        summary += " (fallback)"
    set_stage_status(session, task_id=task_id, stage_name="ingest", status="success", summary=summary)
    return DownloadResult(
        source_metadata=source_metadata,
        output_path=output_path,
        selected_downloader=selected_downloader,
        fallback_used=fallback_used,
        auth_cookie_present=auth_cookie_present,
    )
