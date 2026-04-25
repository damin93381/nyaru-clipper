from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import select


def _reset_runtime_state() -> None:
    try:
        from app.db import reset_db_runtime
    except ModuleNotFoundError:
        return
    reset_db_runtime()


def _create_task(client: TestClient) -> str:
    response = client.post("/api/tasks", json={"source_url": "https://www.bilibili.com/video/BV1retryapi001"})
    assert response.status_code == 201
    return response.json()["task_id"]


def test_retry_endpoint_requeues_failed_stage_on_existing_job(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{db_path}")
    _reset_runtime_state()

    from app.db import session_scope
    from app.main import app
    from app.models import Task, TaskJob, TaskStage

    with TestClient(app) as client:
        task_id = _create_task(client)

        with session_scope() as session:
            task = session.get(Task, task_id)
            assert task is not None
            task.status = "failed"
            session.add(task)

            stages = session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
            for stage in stages:
                if stage.name in {"ingest", "media_prep", "asr"}:
                    stage.status = "success"
                elif stage.name == "translation":
                    stage.status = "failed"
                    stage.summary = "translation_failed"
                else:
                    stage.status = "skipped"
                session.add(stage)

            job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
            job.status = "failed"
            job.stage_name = "translation"
            job.started_at = stages[0].updated_at
            job.finished_at = stages[0].updated_at
            session.add(job)

        retry_response = client.post(f"/api/tasks/{task_id}/retry", json={"stage_name": "translation"})

        assert retry_response.status_code == 202
        assert retry_response.json() == {"task_id": task_id, "retry_stage": "translation", "status": "pending"}

        with session_scope() as session:
            task = session.get(Task, task_id)
            assert task is not None
            job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
            stages = {
                stage.name: stage.status
                for stage in session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
            }
            task_status = task.status
            job_count = len(session.exec(select(TaskJob)).all())
            job_status = job.status
            job_stage_name = job.stage_name
            job_started_at = job.started_at
            job_finished_at = job.finished_at

        assert task_status == "pending"
        assert job_count == 1
        assert job_status == "pending"
        assert job_stage_name == "translation"
        assert job_started_at is None
        assert job_finished_at is None
        assert stages["ingest"] == "success"
        assert stages["media_prep"] == "success"
        assert stages["asr"] == "success"
        assert stages["translation"] == "pending"
        assert stages["highlight"] == "pending"
        assert stages["export"] == "pending"
        assert stages["report"] == "pending"
