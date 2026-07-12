"""Pipeline-run history projected from the legacy task stage state."""

from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session, select

from app.models import PipelineRun, StageRun, TaskStage, utc_now


def create_pipeline_run(session: Session, task_id: str, trigger: str) -> PipelineRun:
    """Create one pending user-visible pipeline execution."""
    run = PipelineRun(id=f"run-{uuid4().hex}", task_id=task_id, status="pending", trigger=trigger)
    session.add(run)
    session.flush()
    return run


def get_pending_pipeline_run(session: Session, task_id: str) -> PipelineRun | None:
    """Return the latest unclaimed execution for a task, if any."""
    return session.exec(
        select(PipelineRun)
        .where(PipelineRun.task_id == task_id)
        .where(PipelineRun.status == "pending")
        .order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc())
    ).first()


def start_pipeline_run(session: Session, run: PipelineRun) -> None:
    """Mark a pending run active when the worker begins its legacy pipeline."""
    if run.status != "pending":
        return
    run.status = "running"
    run.started_at = utc_now()
    session.add(run)


def finish_pipeline_run(session: Session, run: PipelineRun, status: str) -> None:
    """Finalize the user-visible run after the legacy task reaches a terminal state."""
    run.status = status
    run.finished_at = utc_now()
    session.add(run)


def sync_stage_run(session: Session, run_id: str, legacy_stage: TaskStage) -> StageRun:
    """Mirror one legacy stage transition into its selected pipeline run."""
    stage_run = session.exec(
        select(StageRun).where(StageRun.run_id == run_id).where(StageRun.name == legacy_stage.name)
    ).first()
    if stage_run is None:
        stage_run = StageRun(run_id=run_id, name=legacy_stage.name, status=legacy_stage.status)
    stage_run.status = legacy_stage.status
    stage_run.summary = legacy_stage.summary
    stage_run.failure_code = legacy_stage.failure_code
    stage_run.attempts = legacy_stage.attempts
    stage_run.started_at = legacy_stage.started_at
    stage_run.finished_at = legacy_stage.finished_at
    session.add(stage_run)
    session.flush()
    return stage_run
