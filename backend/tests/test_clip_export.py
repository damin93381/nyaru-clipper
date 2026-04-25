from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from sqlmodel import select


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


@pytest.fixture()
def backend_env(tmp_path, monkeypatch) -> dict[str, Path | str]:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{db_path}")
    _reset_runtime_state()
    return {"data_dir": data_dir, "db_path": db_path}


def _create_task(source_url: str) -> str:
    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, source_url)
        return payload["task_id"]


def _seed_export_inputs(data_dir: Path, task_id: str, *, duration_seconds: float) -> int:
    from app.db import session_scope
    from app.models import ClipCandidate
    from app.services.storage import persist_artifact_metadata

    task_root = data_dir / "tasks" / task_id
    source_path = task_root / "raw" / "source.mp4"
    media_probe_path = task_root / "work" / "media-probe.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    media_probe_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"source-video")
    media_probe_path.write_text(
        json.dumps(
            {
                "format": {"duration": str(duration_seconds)},
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    with session_scope() as session:
        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="ingest",
            kind="source_video",
            path=source_path,
            metadata={"output_file_path": str(source_path)},
        )
        persist_artifact_metadata(
            session,
            task_id=task_id,
            stage_name="media_prep",
            kind="media_probe",
            path=media_probe_path,
            metadata={"ffprobe_metadata": {"format": {"duration": str(duration_seconds)}}},
        )
        candidate = ClipCandidate(
            task_id=task_id,
            start_seconds=10.0,
            end_seconds=22.0,
            score=0.91,
            reason="peak-moment",
            status="candidate",
        )
        session.add(candidate)
        session.flush()
        session.refresh(candidate)
        return int(candidate.id)


def test_export_confirmed_range(backend_env, monkeypatch) -> None:
    data_dir = Path(backend_env["data_dir"])
    task_id = _create_task("https://www.bilibili.com/video/BV1hs411c7mW")
    candidate_id = _seed_export_inputs(data_dir, task_id, duration_seconds=120.0)
    commands: list[list[str]] = []

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(list(args))
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"exported-clip")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    from app.db import session_scope
    from app.models import Artifact, ClipCandidate, TaskStage
    from app.services.clip_export import export_confirmed_clip

    with session_scope() as session:
        result = export_confirmed_clip(
            session,
            task_id,
            candidate_id=candidate_id,
            start_s=12.5,
            end_s=20.0,
        )

    assert result.output_path.name == "clip-00012500-00020000.mp4"
    assert result.output_path.exists()
    assert result.start_s == 12.5
    assert result.end_s == 20.0
    assert [command[0] for command in commands] == ["ffmpeg"]
    assert "subtitles" not in " ".join(commands[0])

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "export")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "export")
        ).all()
        candidate = session.exec(select(ClipCandidate).where(ClipCandidate.id == candidate_id)).one()
        stage_status = stage.status
        stage_summary = stage.summary
        candidate_status = candidate.status
        artifact_kinds = {artifact.kind for artifact in artifacts}
        artifact_metadata = json.loads(artifacts[0].metadata_json)

    assert stage_status == "success"
    assert stage_summary == "Exported clip clip-00012500-00020000.mp4"
    assert candidate_status == "exported"
    assert artifact_kinds == {"clip_export"}
    assert artifact_metadata["candidate_id"] == candidate_id
    assert artifact_metadata["start_s"] == 12.5
    assert artifact_metadata["end_s"] == 20.0
    assert artifact_metadata["source_duration_s"] == 120.0


def test_rejects_out_of_bounds_range(backend_env) -> None:
    data_dir = Path(backend_env["data_dir"])
    task_id = _create_task("https://www.bilibili.com/video/BV1is411c7mX")
    candidate_id = _seed_export_inputs(data_dir, task_id, duration_seconds=30.0)

    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.clip_export import ClipExportFailure, export_confirmed_clip

    with session_scope() as session:
        with pytest.raises(ClipExportFailure, match="outside the source duration"):
            export_confirmed_clip(
                session,
                task_id,
                candidate_id=candidate_id,
                start_s=10.0,
                end_s=40.0,
            )

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "export")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "export")
        ).all()
        stage_status = stage.status
        artifact_count = len(artifacts)

    assert stage_status == "pending"
    assert artifact_count == 0
