from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlmodel import select


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def _create_task(data_dir: Path, monkeypatch) -> str:
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{data_dir.parent / 'task-state.sqlite3'}")
    _reset_runtime_state()

    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, "https://www.bilibili.com/video/BV1cd411c7mF")
        return payload["task_id"]


def test_generate_task_report_includes_required_sections(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    task_id = _create_task(data_dir, monkeypatch)

    from app.db import session_scope
    from app.models import ClipCandidate, Task, TaskStage, utc_now
    from app.services.storage import persist_artifact_metadata

    task_root = data_dir / "tasks" / task_id
    export_path = task_root / "exports" / "clip-00012000-00019500.mp4"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_bytes(b"clip")
    source_metadata_path = task_root / "raw" / "source-metadata.json"
    source_metadata_path.parent.mkdir(parents=True, exist_ok=True)
    source_metadata_path.write_text('{"title": "Fixture Stream"}', encoding="utf-8")
    transcript_path = task_root / "work" / "subtitles.zh-ja.json"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("{}", encoding="utf-8")

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "success"
        session.add(task)

        stages = session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
        base_time = utc_now()
        for index, stage in enumerate(stages, start=1):
            stage.status = "success"
            stage.attempts = 2 if stage.name == "translation" else 1
            stage.started_at = base_time + timedelta(seconds=index * 10)
            stage.finished_at = stage.started_at + timedelta(seconds=index)
            stage.summary = f"{stage.name} complete"
            session.add(stage)

        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="ingest",
            kind="source_metadata",
            path=source_metadata_path,
            metadata={"source_metadata": {"title": "Fixture Stream", "uploader": "Tester", "duration": 90.0}},
        )
        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="translation",
            kind="bilingual_transcript_json",
            path=transcript_path,
            metadata={
                "elapsed_seconds": 7.5,
                "model_metadata": {"provider": "hf", "model_name": "fixture-translator"},
            },
        )
        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="export",
            kind="clip_export",
            path=export_path,
            metadata={"candidate_id": 4, "start_s": 12.0, "end_s": 19.5, "source_duration_s": 90.0},
        )
        candidate = ClipCandidate(
            task_id=task_id,
            start_seconds=12.0,
            end_seconds=19.5,
            score=0.87,
            reason="fixture",
            status="confirmed",
        )
        session.add(candidate)
        session.flush()
        candidate_id = candidate.id

    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.reporting import generate_task_report

    with session_scope() as session:
        result = generate_task_report(session, task_id)

    report_text = result.output_path.read_text(encoding="utf-8")
    assert "# Task Report" in report_text
    assert "Fixture Stream" in report_text
    assert "## Source Metadata" in report_text
    assert "## Stage Timings" in report_text
    assert "## Model Metadata" in report_text
    assert "fixture-translator" in report_text
    assert "## Retries" in report_text
    assert "translation" in report_text
    assert "## Artifacts" in report_text
    assert "## Exported Clips" in report_text
    assert "clip-00012000-00019500.mp4" in report_text
    assert "## Clip Candidates" in report_text
    assert f"Candidate {candidate_id}: 12.0s → 19.5s [confirmed] score=0.87" in report_text

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "report")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "report")
        ).all()
        stage_status = stage.status
        stage_summary = stage.summary
        artifact_kinds = {artifact.kind for artifact in artifacts}

    assert stage_status == "success"
    assert stage_summary == f"Generated task report {result.output_path.name}"
    assert artifact_kinds == {"task_report_markdown"}
