# Stale Worker Job Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent abandoned `running` task jobs from blocking the single GPU worker forever by recovering stale jobs before the next claim.

**Architecture:** Add a small worker-side stale-job recovery pass in `backend/app/worker.py` that runs before the existing `running`-job gate. Recovery marks the orphaned task, job, and stage as failed and appends a stage log entry so operators can see why the queue was unblocked.

**Tech Stack:** Python, SQLModel, pytest, SQLite, existing task log helpers

---

### Task 1: Add failing worker recovery tests

**Files:**
- Modify: `backend/tests/test_worker_runtime_warnings.py`
- Test: `backend/tests/test_worker_runtime_warnings.py`

- [ ] **Step 1: Write the failing test for stale running job recovery**

```python
def test_claim_next_job_recovers_stale_running_gpu_job(backend_env, monkeypatch) -> None:
    stale_task_id = _create_task("https://www.bilibili.com/video/BV1stale001")
    pending_task_id = _create_task("https://www.bilibili.com/video/BV1pending001")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage, utc_now
    from app.worker import claim_next_job

    stale_now = utc_now() - timedelta(minutes=10)
    monkeypatch.setenv("APP_WORKER_RUNNING_JOB_STALE_SECONDS", "60")

    with session_scope() as session:
        stale_task = session.get(Task, stale_task_id)
        pending_task = session.get(Task, pending_task_id)
        assert stale_task is not None and pending_task is not None

        stale_task.status = "running"
        stale_task.updated_at = stale_now
        session.add(stale_task)

        stale_job = session.exec(select(TaskJob).where(TaskJob.task_id == stale_task_id)).one()
        stale_job.status = "running"
        stale_job.stage_name = "ingest"
        stale_job.started_at = stale_now
        stale_job.updated_at = stale_now
        stale_job.finished_at = None
        session.add(stale_job)

        stale_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == stale_task_id).where(TaskStage.name == "ingest")
        ).one()
        stale_stage.status = "running"
        stale_stage.started_at = stale_now
        stale_stage.updated_at = stale_now
        stale_stage.finished_at = None
        session.add(stale_stage)

    claimed = claim_next_job()

    assert claimed is not None
    assert claimed.task_id == pending_task_id
    assert claimed.stage_name == "ingest"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_worker_runtime_warnings.py::test_claim_next_job_recovers_stale_running_gpu_job -v`
Expected: FAIL because `claim_next_job()` returns `None` while the stale running job still blocks the queue.

- [ ] **Step 3: Write the fresh-running guard test**

```python
def test_claim_next_job_keeps_fresh_running_gpu_job_blocking_queue(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1fresh001")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage, utc_now
    from app.worker import claim_next_job

    fresh_now = utc_now()
    monkeypatch.setenv("APP_WORKER_RUNNING_JOB_STALE_SECONDS", "3600")

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "running"
        task.updated_at = fresh_now
        session.add(task)

        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        job.status = "running"
        job.stage_name = "ingest"
        job.started_at = fresh_now
        job.updated_at = fresh_now
        job.finished_at = None
        session.add(job)

        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        stage.status = "running"
        stage.started_at = fresh_now
        stage.updated_at = fresh_now
        stage.finished_at = None
        session.add(stage)

    claimed = claim_next_job()

    assert claimed is None
```

- [ ] **Step 4: Run both tests and verify the stale-recovery test fails while the fresh-block test passes**

Run: `pytest backend/tests/test_worker_runtime_warnings.py::test_claim_next_job_recovers_stale_running_gpu_job backend/tests/test_worker_runtime_warnings.py::test_claim_next_job_keeps_fresh_running_gpu_job_blocking_queue -v`
Expected: one FAIL (stale recovery missing) and one PASS (fresh running job still blocks).

### Task 2: Implement stale job recovery in the worker

**Files:**
- Modify: `backend/app/worker.py`
- Test: `backend/tests/test_worker_runtime_warnings.py`

- [ ] **Step 1: Add worker stale-job configuration and recovery helpers**

```python
from datetime import timedelta
import os


def _get_running_job_stale_seconds() -> int:
    raw_value = os.getenv("APP_WORKER_RUNNING_JOB_STALE_SECONDS", "300")
    try:
        return max(1, int(raw_value))
    except ValueError:
        return 300


def _recover_stale_running_jobs(session) -> None:
    stale_before = utc_now() - timedelta(seconds=_get_running_job_stale_seconds())
    running_jobs = session.exec(
        select(TaskJob).where(TaskJob.gpu_bound.is_(True)).where(TaskJob.status == "running")
    ).all()
    for job in running_jobs:
        if job.updated_at > stale_before:
            continue
        _mark_job_stale_failed(session, job)
```

- [ ] **Step 2: Add the stale failure mutation and log write**

```python
def _mark_job_stale_failed(session, job: TaskJob) -> None:
    now = utc_now()
    task = session.get(Task, job.task_id)
    stage = session.exec(
        select(TaskStage)
        .where(TaskStage.task_id == job.task_id)
        .where(TaskStage.name == job.stage_name)
    ).first()

    job.status = "failed"
    job.finished_at = now
    job.updated_at = now
    session.add(job)

    if task is not None:
        task.status = "failed"
        task.updated_at = now
        session.add(task)

    if stage is not None:
        stage.status = "failed"
        stage.summary = "Recovered stale running job"
        stage.finished_at = now
        stage.updated_at = now
        session.add(stage)
        append_stage_log(
            log_file_for_stage(job.task_id, job.stage_name),
            "worker:recovered stale running job",
        )
```

- [ ] **Step 3: Run recovery before the existing running-job gate**

```python
with session_scope() as session:
    _recover_stale_running_jobs(session)
    running_gpu_job = session.exec(
        select(TaskJob).where(TaskJob.gpu_bound.is_(True)).where(TaskJob.status == "running")
    ).first()
```

- [ ] **Step 4: Run the worker recovery tests to verify they pass**

Run: `pytest backend/tests/test_worker_runtime_warnings.py::test_claim_next_job_recovers_stale_running_gpu_job backend/tests/test_worker_runtime_warnings.py::test_claim_next_job_keeps_fresh_running_gpu_job_blocking_queue -v`
Expected: PASS

### Task 3: Verify operator-visible recovery behavior

**Files:**
- Modify: `backend/tests/test_worker_runtime_warnings.py`
- Test: `backend/tests/test_worker_runtime_warnings.py`

- [ ] **Step 1: Extend the stale recovery test to assert DB and log side effects**

```python
    with session_scope() as session:
        stale_task = session.get(Task, stale_task_id)
        stale_job = session.exec(select(TaskJob).where(TaskJob.task_id == stale_task_id)).one()
        stale_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == stale_task_id).where(TaskStage.name == "ingest")
        ).one()

    assert stale_task is not None
    assert stale_task.status == "failed"
    assert stale_job.status == "failed"
    assert stale_stage.status == "failed"
    assert stale_stage.summary == "Recovered stale running job"

    ingest_log = Path(backend_env["data_dir"]) / "tasks" / stale_task_id / "logs" / "ingest.log"
    assert "worker:recovered stale running job" in ingest_log.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the focused worker test file**

Run: `pytest backend/tests/test_worker_runtime_warnings.py -v`
Expected: PASS

- [ ] **Step 3: Run the adjacent pipeline tests as regression coverage**

Run: `pytest backend/tests/test_task_runner.py backend/tests/test_downloader.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-04-29-stale-worker-job-recovery.md backend/app/worker.py backend/tests/test_worker_runtime_warnings.py
git commit -m "fix: recover stale running worker jobs"
```
