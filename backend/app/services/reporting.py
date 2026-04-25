from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import Artifact, ClipCandidate
from app.repositories.tasks import get_task_record
from app.services.pipeline_support import set_stage_status
from app.services.storage import ensure_task_dirs, persist_artifact_metadata


@dataclass(slots=True)
class TaskReportResult:
    task_id: str
    output_path: Path
    artifact_id: int


def generate_task_report(session: Session, task_id: str) -> TaskReportResult:
    record = get_task_record(session, task_id)
    if record is None:
        raise ValueError(f"Unknown task_id: {task_id}")

    task_dirs = ensure_task_dirs(task_id)
    output_path = task_dirs["reports"] / "task-report.md"
    exported_clips = _collect_exported_clips(record.artifacts)
    report_text = _render_report(session, record, exported_clips)
    output_path.write_text(report_text, encoding="utf-8")

    artifact = _persist_report_artifact(session, task_id=task_id, output_path=output_path)
    set_stage_status(
        session,
        task_id=task_id,
        stage_name="report",
        status="success",
        summary=f"Generated task report {output_path.name}",
    )
    return TaskReportResult(task_id=task_id, output_path=output_path, artifact_id=int(artifact.id))


def _render_report(session: Session, record, exported_clips: list[dict[str, Any]]) -> str:
    source_metadata = _collect_source_metadata(record.artifacts)
    model_metadata = _collect_model_metadata(record.artifacts)
    retries = [stage for stage in record.stages if stage.attempts > 1]
    failed_stages = [stage for stage in record.stages if stage.status == "failed"]
    clip_candidates = _collect_clip_candidates(session, record.task.id)

    lines: list[str] = [
        "# Task Report",
        "",
        "## Task",
        "",
        f"- Task ID: `{record.task.id}`",
        f"- Source URL: {record.task.source_url}",
        f"- Normalized Source URL: {record.task.normalized_source_url}",
        f"- Source Video ID: {record.task.source_video_id or 'n/a'}",
        f"- Task Status: {record.task.status}",
        "",
        "## Source Metadata",
        "",
    ]
    if source_metadata:
        for key, value in source_metadata.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- No source metadata recorded")

    lines.extend(["", "## Stage Timings", "", "| Stage | Status | Attempts | Started | Finished | Summary |", "| --- | --- | ---: | --- | --- | --- |"])
    for stage in record.stages:
        lines.append(
            "| {name} | {status} | {attempts} | {started} | {finished} | {summary} |".format(
                name=stage.name,
                status=stage.status,
                attempts=stage.attempts,
                started=stage.started_at.isoformat() if stage.started_at else "-",
                finished=stage.finished_at.isoformat() if stage.finished_at else "-",
                summary=stage.summary or "-",
            )
        )

    lines.extend(["", "## Model Metadata", ""])
    if model_metadata:
        for entry in model_metadata:
            lines.append(f"- {entry['stage_name']}/{entry['kind']}: {json.dumps(entry['model_metadata'], ensure_ascii=False, sort_keys=True)}")
    else:
        lines.append("- No model metadata recorded")

    lines.extend(["", "## Retries", ""])
    if retries:
        for stage in retries:
            lines.append(f"- {stage.name}: {stage.attempts} attempts")
    else:
        lines.append("- No retries recorded")

    lines.extend(["", "## Failures", ""])
    if failed_stages:
        for stage in failed_stages:
            lines.append(f"- {stage.name}: {stage.summary or stage.status}")
    else:
        lines.append("- No failed stages recorded")

    lines.extend(["", "## Artifacts", ""])
    if record.artifacts:
        for artifact in record.artifacts:
            lines.append(f"- {artifact.stage_name}/{artifact.kind}: `{artifact.path}`")
    else:
        lines.append("- No artifacts recorded")

    lines.extend(["", "## Exported Clips", ""])
    if exported_clips:
        for clip in exported_clips:
            lines.append(
                f"- `{clip['filename']}` ({clip['start_s']}s → {clip['end_s']}s) from candidate {clip['candidate_id']}"
            )
    else:
        lines.append("- No exported clips recorded")

    lines.extend(["", "## Clip Candidates", ""])
    if clip_candidates:
        for candidate in clip_candidates:
            lines.append(
                f"- Candidate {candidate['id']}: {candidate['start_s']}s → {candidate['end_s']}s [{candidate['status']}] score={candidate['score']}"
            )
    else:
        lines.append("- No clip candidates recorded")

    return "\n".join(lines) + "\n"


def _collect_source_metadata(artifacts: list[Artifact]) -> dict[str, Any]:
    for artifact in reversed(artifacts):
        if artifact.kind == "source_metadata":
            metadata = json.loads(artifact.metadata_json)
            source_metadata = metadata.get("source_metadata")
            if isinstance(source_metadata, dict):
                return source_metadata
    return {}


def _collect_model_metadata(artifacts: list[Artifact]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for artifact in artifacts:
        metadata = json.loads(artifact.metadata_json)
        model_metadata = metadata.get("model_metadata")
        if isinstance(model_metadata, dict):
            entries.append(
                {
                    "stage_name": artifact.stage_name,
                    "kind": artifact.kind,
                    "model_metadata": model_metadata,
                }
            )
    return entries


def _collect_exported_clips(artifacts: list[Artifact]) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact.kind != "clip_export":
            continue
        metadata = json.loads(artifact.metadata_json)
        clips.append(
            {
                "filename": metadata.get("filename") or Path(artifact.path).name,
                "candidate_id": metadata.get("candidate_id"),
                "start_s": metadata.get("start_s"),
                "end_s": metadata.get("end_s"),
            }
        )
    return clips


def _collect_clip_candidates(session: Session, task_id: str) -> list[dict[str, Any]]:
    candidates = session.exec(
        select(ClipCandidate).where(ClipCandidate.task_id == task_id).order_by(ClipCandidate.id)
    ).all()
    return [
        {
            "id": candidate.id,
            "start_s": candidate.start_seconds,
            "end_s": candidate.end_seconds,
            "status": candidate.status,
            "score": candidate.score,
        }
        for candidate in candidates
    ]


def _persist_report_artifact(session: Session, *, task_id: str, output_path: Path) -> Artifact:
    existing = session.exec(
        select(Artifact)
        .where(Artifact.task_id == task_id)
        .where(Artifact.stage_name == "report")
        .where(Artifact.kind == "task_report_markdown")
        .where(Artifact.path == str(output_path))
    ).first()
    metadata = {"filename": output_path.name}
    if existing is not None:
        existing.metadata_json = json.dumps(metadata, sort_keys=True)
        session.add(existing)
        session.flush()
        session.refresh(existing)
        return existing
    return persist_artifact_metadata(
        session,
        task_id=task_id,
        stage_name="report",
        kind="task_report_markdown",
        path=output_path,
        metadata=metadata,
    )
