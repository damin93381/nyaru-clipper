from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from app.models import utc_now
from app.services.asr_whisperx import (
    ASR_PIPELINE_PHASES,
    AsrArtifactPaths,
    AsrPhaseResult,
    AsrPipelineError,
    AsrPipelineObserver,
    AsrPipelineResult,
    execute_asr_pipeline,
)
from app.services.storage import ensure_task_dirs, get_tasks_root
from app.settings import Settings, get_settings

ASR_CHILD_MODULE = "app.services.asr_child_runner"
ASR_RESULT_MANIFEST_FILENAME = "asr-result.json"


@dataclass(slots=True)
class AsrChildRunResult:
    status: str
    manifest_path: Path


TASK_ID_PATTERN = re.compile(r"^task-[a-f0-9]{12}$")


class JsonlAsrObserver(AsrPipelineObserver):
    def __init__(self, stream: TextIO):
        self._stream = stream

    def phase_start(self, phase: str, *, phase_index: int, phase_count: int, message: str) -> None:
        self._emit(
            {
                "event": "phase_start",
                "phase": phase,
                "phase_index": phase_index,
                "phase_count": phase_count,
                "message": message,
                "ts": _utc_isoformat(),
            }
        )

    def heartbeat(
        self,
        phase: str,
        *,
        phase_index: int,
        phase_count: int,
        elapsed_ms: int,
        message: str,
    ) -> None:
        self._emit(
            {
                "event": "heartbeat",
                "phase": phase,
                "phase_index": phase_index,
                "phase_count": phase_count,
                "elapsed_ms": elapsed_ms,
                "message": message,
                "ts": _utc_isoformat(),
            }
        )

    def phase_complete(self, phase: str, *, phase_index: int, phase_count: int, elapsed_ms: int) -> None:
        self._emit(
            {
                "event": "phase_complete",
                "phase": phase,
                "phase_index": phase_index,
                "phase_count": phase_count,
                "elapsed_ms": elapsed_ms,
                "ts": _utc_isoformat(),
            }
        )

    def emit_failure(self, *, phase: str, code: str, message: str) -> None:
        self._emit(
            {
                "event": "failure",
                "phase": phase,
                "code": code,
                "message": message,
                "ts": _utc_isoformat(),
            }
        )

    def emit_success(self, *, phase: str, elapsed_ms_total: int, manifest_path: Path) -> None:
        self._emit(
            {
                "event": "success",
                "phase": phase,
                "elapsed_ms_total": elapsed_ms_total,
                "manifest_path": str(manifest_path.resolve()),
                "ts": _utc_isoformat(),
            }
        )

    def _emit(self, payload: dict[str, object]) -> None:
        self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._stream.flush()


def build_asr_child_command(task_id: str, *, python_executable: str | None = None) -> list[str]:
    executable = python_executable or sys.executable
    return [executable, "-m", ASR_CHILD_MODULE, task_id]


def run_asr_child(
    task_id: str,
    *,
    settings: Settings | None = None,
    stream: TextIO | None = None,
) -> AsrChildRunResult:
    effective_settings = settings or get_settings()
    output_stream = stream or sys.stdout
    observer = JsonlAsrObserver(output_stream)
    work_dir = _resolve_child_work_dir(task_id)
    audio_path = work_dir / "asr-input.wav"
    manifest_path = work_dir / ASR_RESULT_MANIFEST_FILENAME

    try:
        pipeline_result = execute_asr_pipeline(
            audio_path=audio_path,
            work_dir=work_dir,
            settings=effective_settings,
            observer=observer,
        )
    except AsrPipelineError as exc:
        _write_manifest(
            manifest_path,
            _build_failure_manifest(
                elapsed_ms_total=exc.elapsed_ms_total,
                phases=exc.phases,
                artifacts=exc.artifacts,
                model_metadata=exc.model_metadata,
                error={
                    "code": exc.code,
                    "message": str(exc),
                    "phase": exc.phase,
                },
            ),
        )
        observer.emit_failure(phase=exc.phase, code=exc.code, message=str(exc))
        return AsrChildRunResult(status="failed", manifest_path=manifest_path)

    _write_manifest(manifest_path, _build_success_manifest(pipeline_result))
    observer.emit_success(
        phase=ASR_PIPELINE_PHASES[-1],
        elapsed_ms_total=pipeline_result.elapsed_ms_total,
        manifest_path=manifest_path,
    )
    return AsrChildRunResult(status="success", manifest_path=manifest_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ASR child pipeline for a single task work directory.")
    parser.add_argument("task_id", help="Task identifier whose work directory contains asr-input.wav")
    args = parser.parse_args(argv)
    result = run_asr_child(args.task_id)
    return 0 if result.status == "success" else 1


def _build_success_manifest(result: AsrPipelineResult) -> dict[str, object]:
    return {
        "status": "success",
        "elapsed_ms_total": result.elapsed_ms_total,
        "phases": _serialize_phases(result.phases),
        "artifacts": _serialize_artifacts(
            AsrArtifactPaths(
                audio_path=result.audio_path,
                transcript_path=result.transcript_path,
                subtitle_path=result.subtitle_path,
                raw_alignment_path=result.raw_alignment_path,
            )
        ),
        "model_metadata": dict(result.model_metadata),
        "error": None,
    }


def _build_failure_manifest(
    *,
    elapsed_ms_total: int,
    phases: list[AsrPhaseResult],
    artifacts: AsrArtifactPaths,
    model_metadata: dict[str, object],
    error: dict[str, object],
) -> dict[str, object]:
    return {
        "status": "failed",
        "elapsed_ms_total": elapsed_ms_total,
        "phases": _serialize_phases(phases),
        "artifacts": _serialize_artifacts(artifacts),
        "model_metadata": dict(model_metadata),
        "error": error,
    }


def _serialize_phases(phases: list[AsrPhaseResult]) -> list[dict[str, object]]:
    return [
        {
            "name": phase.name,
            "status": phase.status,
            "elapsed_ms": phase.elapsed_ms,
        }
        for phase in phases
    ]


def _serialize_artifacts(artifacts: AsrArtifactPaths) -> dict[str, str | None]:
    return {
        "audio_path": str(artifacts.audio_path.resolve()),
        "transcript_path": _serialize_optional_path(artifacts.transcript_path),
        "subtitle_path": _serialize_optional_path(artifacts.subtitle_path),
        "raw_alignment_path": _serialize_optional_path(artifacts.raw_alignment_path),
    }


def _serialize_optional_path(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path.resolve())


def _write_manifest(manifest_path: Path, payload: dict[str, object]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_child_work_dir(task_id: str) -> Path:
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise ValueError(f"Invalid task_id for ASR child runner: {task_id!r}")
    work_dir = ensure_task_dirs(task_id)["work"].resolve()
    tasks_root = get_tasks_root().resolve()
    work_dir.relative_to(tasks_root)
    return work_dir


def _utc_isoformat() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
