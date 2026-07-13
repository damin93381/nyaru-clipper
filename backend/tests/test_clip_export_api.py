from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
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


@pytest.fixture()
def client(backend_env) -> TestClient:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _seed_task_with_candidate(data_dir: Path) -> tuple[str, int]:
    from app.db import init_db, session_scope
    from app.models import ClipCandidate
    from app.repositories.tasks import create_task
    from app.services.storage import persist_artifact_metadata

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, "https://www.bilibili.com/video/BV1ab411c7mE")
        task_id = payload["task_id"]
        task_root = data_dir / "tasks" / task_id
        source_path = task_root / "raw" / "source.mp4"
        media_probe_path = task_root / "work" / "media-probe.json"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        media_probe_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"source-video")
        media_probe_path.write_text(
            json.dumps({"format": {"duration": "90.0"}}, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
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
            metadata={"ffprobe_metadata": {"format": {"duration": "90.0"}}},
        )
        candidate = ClipCandidate(
            task_id=task_id,
            start_seconds=11.0,
            end_seconds=18.0,
            score=0.9,
            reason="peak-moment",
            status="candidate",
        )
        session.add(candidate)
        session.flush()
        session.refresh(candidate)
        return task_id, int(candidate.id)


def test_post_clips_exports_confirmed_candidate(client: TestClient, backend_env, monkeypatch) -> None:
    task_id, candidate_id = _seed_task_with_candidate(Path(backend_env["data_dir"]))

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"clip")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    response = client.post(
        f"/api/tasks/{task_id}/clips",
        json={"candidate_id": candidate_id, "start_s": 12.0, "end_s": 19.5},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["task_id"] == task_id
    assert body["candidate_id"] == candidate_id
    assert body["start_s"] == 12.0
    assert body["end_s"] == 19.5
    assert body["filename"] == "clip-00012000-00019500.mp4"
    assert body["path"] == f"/api/tasks/{task_id}/artifacts/{body['artifact_id']}/content/clip-00012000-00019500.mp4"

    artifact_response = client.get(body["path"])

    assert artifact_response.status_code == 200
    assert artifact_response.content == b"clip"
    assert "attachment; filename=\"clip-00012000-00019500.mp4\"" in artifact_response.headers["content-disposition"]

    from app.db import session_scope
    from app.models import Artifact, ClipCandidate

    with session_scope() as session:
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "export")
        ).all()
        candidate = session.exec(select(ClipCandidate).where(ClipCandidate.id == candidate_id)).one()
        artifact_kinds = {artifact.kind for artifact in artifacts}
        candidate_status = candidate.status

    assert artifact_kinds == {"clip_export"}
    assert candidate_status == "exported"


def test_post_clips_persists_public_stage_event_after_successful_manual_export(
    client: TestClient, backend_env, monkeypatch
) -> None:
    # Given: a manually exportable candidate and an ffmpeg invocation that creates its output.
    task_id, candidate_id = _seed_task_with_candidate(Path(backend_env["data_dir"]))

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"clip")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    # When: the v1 clip export route completes the manual export transaction.
    response = client.post(f"/api/tasks/{task_id}/clips", json={"candidate_id": candidate_id})

    # Then: the committed stage state has a replayable public projection.
    from app.db import session_scope
    from app.models import WorkstationEvent

    with session_scope() as session:
        events = session.exec(
            select(WorkstationEvent)
            .where(WorkstationEvent.entity_id == task_id)
            .where(WorkstationEvent.event_type == "stage.updated")
        ).all()
        payloads = [json.loads(event.payload_json) for event in events]
    assert response.status_code == 201
    assert {
        "task_id": task_id,
        "stage_name": "export",
        "status": "success",
        "failure_code": None,
        "attempts": 0,
    } in payloads


def test_post_clips_persists_task_and_stage_events_after_failed_manual_export(
    client: TestClient, backend_env, monkeypatch
) -> None:
    # Given: an exportable candidate whose ffmpeg command fails.
    task_id, candidate_id = _seed_task_with_candidate(Path(backend_env["data_dir"]))

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="ffmpeg failed")

    monkeypatch.setattr("subprocess.run", fake_run)

    # When: the v1 clip export route handles that failed manual export.
    response = client.post(f"/api/tasks/{task_id}/clips", json={"candidate_id": candidate_id})

    # Then: its internally committed failed task and export stage are both replayable.
    from app.db import session_scope
    from app.models import WorkstationEvent

    with session_scope() as session:
        events = session.exec(select(WorkstationEvent).where(WorkstationEvent.entity_id == task_id)).all()
        payloads_by_type = [(event.event_type, json.loads(event.payload_json)) for event in events]
    assert response.status_code == 400
    assert ("task.updated", {"task_id": task_id, "status": "failed"}) in payloads_by_type
    assert (
        "stage.updated",
        {
            "task_id": task_id,
            "stage_name": "export",
            "status": "failed",
            "failure_code": None,
            "attempts": 0,
        },
    ) in payloads_by_type


def test_post_clips_rejects_invalid_range(client: TestClient, backend_env) -> None:
    task_id, candidate_id = _seed_task_with_candidate(Path(backend_env["data_dir"]))

    response = client.post(
        f"/api/tasks/{task_id}/clips",
        json={"candidate_id": candidate_id, "start_s": 12.0, "end_s": 120.0},
    )

    assert response.status_code == 400
    assert "outside the source duration" in response.json()["detail"]
