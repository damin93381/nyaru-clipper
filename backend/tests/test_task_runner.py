from __future__ import annotations

import json
import subprocess
import threading
import time
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


def _prepare_asr_input_audio(data_dir: Path, task_id: str) -> Path:
    from app.services.media_chunks import build_media_chunk_manifest, write_media_chunk_manifest_atomically

    work_dir = data_dir / "tasks" / task_id / "work"
    manifest = build_media_chunk_manifest(1.0, work_dir=work_dir)
    audio_path = manifest.chunks[0].audio_path
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"RIFFfixture")
    write_media_chunk_manifest_atomically(work_dir / "media-chunks.json", manifest)
    return audio_path


def _write_asr_success_outputs(data_dir: Path, task_id: str) -> dict[str, Path]:
    from app.services.media_chunks import load_media_chunk_manifest

    work_dir = data_dir / "tasks" / task_id / "work"
    chunk = load_media_chunk_manifest(work_dir / "media-chunks.json").chunks[0]
    chunk_dir = work_dir / "asr-chunks" / chunk.id
    chunk_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = chunk_dir / "asr-segments.json"
    subtitle_path = chunk_dir / "subtitles.zh.srt"
    raw_alignment_path = chunk_dir / "asr-alignment-raw.json"

    transcript_path.write_text(
        json.dumps(
            {
                "segments": [
                    {"id": "seg-0001", "start_seconds": 0.0, "end_seconds": 0.5, "text": "你好"},
                    {"id": "seg-0002", "start_seconds": 0.5, "end_seconds": 1.0, "text": "世界"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    raw_alignment_path.write_text(json.dumps({"language": "zh"}, ensure_ascii=False), encoding="utf-8")
    return {
        "transcript_path": transcript_path,
        "subtitle_path": subtitle_path,
        "raw_alignment_path": raw_alignment_path,
    }


def test_asr_runner_executes_missing_chunks_sequentially_and_merges_global_timestamps(backend_env, monkeypatch) -> None:
    # Given: a three-chunk media manifest and a valid cached first chunk.
    task_id = _create_task("https://www.bilibili.com/video/BV1chunkrunner001")
    data_dir = Path(backend_env["data_dir"])
    from app.services.media_chunks import build_media_chunk_manifest, write_media_chunk_manifest_atomically

    work_dir = data_dir / "tasks" / task_id / "work"
    manifest = build_media_chunk_manifest(601.25, work_dir=work_dir)
    for chunk in manifest.chunks:
        chunk.audio_path.parent.mkdir(parents=True, exist_ok=True)
        chunk.audio_path.write_bytes(b"RIFFfixture")
    write_media_chunk_manifest_atomically(work_dir / "media-chunks.json", manifest)

    def write_chunk(index: int) -> Path:
        chunk = manifest.chunks[index]
        chunk_dir = work_dir / "asr-chunks" / chunk.id
        chunk_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = chunk_dir / "asr-segments.json"
        subtitle_path = chunk_dir / "subtitles.zh.srt"
        raw_path = chunk_dir / "asr-alignment-raw.json"
        transcript_path.write_text(
            json.dumps(
                {
                    "segments": [
                        {"id": "seg-0001", "start_seconds": 0.0, "end_seconds": 1.0, "text": f"片段{index}"}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        subtitle_path.write_text("", encoding="utf-8")
        raw_path.write_text("{}", encoding="utf-8")
        manifest_path = chunk_dir / "asr-result.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "status": "success",
                    "elapsed_ms_total": 100,
                    "phases": [],
                    "artifacts": {
                        "audio_path": str(chunk.audio_path.resolve()),
                        "transcript_path": str(transcript_path.resolve()),
                        "subtitle_path": str(subtitle_path.resolve()),
                        "raw_alignment_path": str(raw_path.resolve()),
                    },
                    "model_metadata": {"language": "zh"},
                    "error": None,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return manifest_path

    write_chunk(0)
    executed_indices: list[int] = []

    from app.db import session_scope
    from app.services.pipeline_support import StructuredProcessGroupResult
    import app.services.task_runner as task_runner

    def fake_child(session, *, args, on_event=None, **kwargs):
        index = int(args[-1])
        executed_indices.append(index)
        manifest_path = write_chunk(index)
        event = {"event": "success", "phase": "persist", "elapsed_ms_total": 100, "manifest_path": str(manifest_path)}
        if on_event is not None:
            on_event(event)
        return StructuredProcessGroupResult(
            completed_process=subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr=""),
            events=[event],
            latest_event=event,
        )

    monkeypatch.setattr(task_runner, "run_tracked_structured_process_group_command", fake_child)

    # When: ASR executes from the media preparation checkpoint.
    with session_scope() as session:
        directive = task_runner._execute_asr_subprocess(session, task_id)

    # Then: only uncached chunks run in order and canonical output uses source-global timestamps.
    merged = json.loads((work_dir / "asr-segments.json").read_text(encoding="utf-8"))
    assert directive.summary == "Generated aligned transcript and Chinese subtitles"
    assert executed_indices == [1, 2]
    assert [(row["id"], row["start_seconds"]) for row in merged["segments"]] == [
        ("seg-000001", 0.0),
        ("seg-000002", 300.0),
        ("seg-000003", 600.0),
    ]


def test_duplicate_submission_returns_existing_task_after_source_video_id_is_discovered(backend_env) -> None:
    task_id = _create_task("https://www.bilibili.com/bangumi/play/ep424242")

    from app.db import session_scope
    from app.models import Task, TaskJob
    from app.repositories.tasks import create_task

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.source_video_id = "BV1dedupe123"
        session.add(task)

    with session_scope() as session:
        payload, created = create_task(session, "https://www.bilibili.com/video/BV1dedupe123?p=9")
        task_count = len(session.exec(select(Task)).all())
        job_count = len(session.exec(select(TaskJob)).all())

    assert created is False
    assert payload["task_id"] == task_id
    assert payload["created"] is False
    assert task_count == 1
    assert job_count == 1


def test_run_task_pipeline_executes_canonical_stage_order_and_checkpoints_each_success(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runner001")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage
    import app.services.task_runner as task_runner

    called: list[str] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str) -> None:
            assert current_task_id == task_id
            called.append(stage_name)
            if stage_name == "ingest":
                task = session.get(Task, current_task_id)
                assert task is not None
                task.source_video_id = "BV1runner001"
                session.add(task)

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    with session_scope() as session:
        result = task_runner.run_task_pipeline(session, task_id)

    assert result.final_status == "success"
    assert called == list(task_runner.CANONICAL_STAGE_ORDER)

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        stages = session.exec(select(TaskStage).where(TaskStage.task_id == task_id).order_by(TaskStage.id)).all()
        task_status = task.status
        task_source_video_id = task.source_video_id
        job_status = job.status
        job_stage_name = job.stage_name
        stage_names = [stage.name for stage in stages]
        stage_statuses = [stage.status for stage in stages]
        stage_attempts = [stage.attempts for stage in stages]
        stage_started = [stage.started_at for stage in stages]
        stage_finished = [stage.finished_at for stage in stages]

    assert task_status == "success"
    assert task_source_video_id == "BV1runner001"
    assert job_status == "success"
    assert job_stage_name == "report"
    assert stage_names == list(task_runner.CANONICAL_STAGE_ORDER)
    assert stage_statuses == ["success"] * len(task_runner.CANONICAL_STAGE_ORDER)
    assert stage_attempts == [1] * len(task_runner.CANONICAL_STAGE_ORDER)
    assert all(value is not None for value in stage_started)
    assert all(value is not None for value in stage_finished)


def test_run_task_pipeline_keeps_upstream_success_and_failure_summary(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runner002")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage
    from app.repositories.tasks import list_task_log_summaries
    import app.services.task_runner as task_runner

    called: list[str] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str) -> None:
            called.append(stage_name)
            if stage_name == "translation":
                raise RuntimeError("translation exploded")

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    with pytest.raises(RuntimeError, match="translation exploded"):
        with session_scope() as session:
            task_runner.run_task_pipeline(session, task_id)

    assert called == ["ingest", "media_prep", "asr", "translation"]

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        stages = {
            stage.name: stage
            for stage in session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
        }
        log_summaries = list_task_log_summaries(session, task_id)
        task_status = task.status
        job_status = job.status
        job_stage_name = job.stage_name
        stage_statuses = {name: stage.status for name, stage in stages.items()}
        translation_summary = stages["translation"].summary

    assert task_status == "failed"
    assert job_status == "failed"
    assert job_stage_name == "translation"
    assert stage_statuses["ingest"] == "success"
    assert stage_statuses["media_prep"] == "success"
    assert stage_statuses["asr"] == "success"
    assert stage_statuses["translation"] == "failed"
    assert translation_summary == "translation exploded"
    assert stage_statuses["highlight"] == "pending"
    assert stage_statuses["export"] == "pending"
    assert stage_statuses["report"] == "pending"
    assert any(
        entry["stage_name"] == "translation" and "translation exploded" in (entry["summary"] or "")
        for entry in log_summaries
    )


def test_worker_iteration_binds_execution_context_and_clears_control_after_success(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runnercontrol001")

    from app.db import session_scope
    import app.services.task_runner as task_runner
    from app.worker import run_worker_iteration

    observed_contexts: list[dict[str, str | None]] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str) -> None:
            from app.services.task_control import ensure_current_execution_context, get_execution_context

            ensure_current_execution_context(session, task_id=current_task_id)
            context = get_execution_context(session)
            assert isinstance(context, dict)
            observed_contexts.append(
                {
                    "stage_name": stage_name,
                    "task_id": context.get("task_id"),
                    "execution_token": context.get("execution_token"),
                }
            )

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    claimed = run_worker_iteration()

    assert claimed is not None
    assert claimed.task_id == task_id
    assert [entry["stage_name"] for entry in observed_contexts] == list(task_runner.CANONICAL_STAGE_ORDER)
    assert all(entry["task_id"] == task_id for entry in observed_contexts)
    assert all(entry["execution_token"] for entry in observed_contexts)

    from app.models import TaskExecutionControl

    with session_scope() as session:
        control = session.get(TaskExecutionControl, task_id)
        assert control is not None
        execution_token = control.execution_token
        active_process_group_id = control.active_process_group_id
        cancel_requested = control.cancel_requested
        force_kill_requested = control.force_kill_requested

    assert execution_token is None
    assert active_process_group_id is None
    assert cancel_requested is False
    assert force_kill_requested is False


def test_run_task_pipeline_finalizes_stage_boundary_cancel_without_starting_next_stage(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runnercontrol002")

    from app.db import session_scope
    from app.models import Task, TaskExecutionControl, TaskJob, TaskStage
    import app.services.task_runner as task_runner
    from app.services.task_control import activate_execution, request_cancel

    called: list[str] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str) -> None:
            called.append(stage_name)
            if stage_name == "ingest":
                request_cancel(session, task_id=current_task_id)

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    with session_scope() as session:
        activate_execution(session, task_id=task_id, execution_token="token-cancel-boundary")
        result = task_runner.run_task_pipeline(
            session,
            task_id,
            start_stage_name="ingest",
            execution_token="token-cancel-boundary",
        )

    assert result.final_status == "cancelled"
    assert result.completed_stages == ["ingest"]
    assert called == ["ingest"]

    with session_scope() as session:
        task = session.get(Task, task_id)
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        ingest_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        media_prep_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "media_prep")
        ).one()
        control = session.get(TaskExecutionControl, task_id)
        task_status = task.status if task is not None else None
        job_status = job.status
        ingest_status = ingest_stage.status
        media_prep_status = media_prep_stage.status
        assert control is not None
        execution_token = control.execution_token

    assert task_status == "cancelled"
    assert job_status == "cancelled"
    assert ingest_status == "success"
    assert media_prep_status == "pending"
    assert execution_token is None


def test_run_task_pipeline_stops_cleanly_when_execution_token_is_superseded(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1runnercontrol003")

    from app.db import session_scope
    from app.models import Task, TaskExecutionControl, TaskJob, TaskStage
    import app.services.task_runner as task_runner
    from app.services.task_control import activate_execution

    called: list[str] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str) -> None:
            called.append(stage_name)
            if stage_name == "ingest":
                activate_execution(session, task_id=current_task_id, execution_token="token-new")

        return _handler

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {stage_name: build_handler(stage_name) for stage_name in task_runner.CANONICAL_STAGE_ORDER},
    )

    with session_scope() as session:
        activate_execution(session, task_id=task_id, execution_token="token-old")
        result = task_runner.run_task_pipeline(
            session,
            task_id,
            start_stage_name="ingest",
            execution_token="token-old",
        )

    assert result.final_status == "running"
    assert result.completed_stages == []
    assert called == ["ingest"]

    with session_scope() as session:
        task = session.get(Task, task_id)
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        ingest_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "ingest")
        ).one()
        media_prep_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "media_prep")
        ).one()
        control = session.get(TaskExecutionControl, task_id)
        task_status = task.status if task is not None else None
        job_status = job.status
        ingest_status = ingest_stage.status
        media_prep_status = media_prep_stage.status
        execution_token = control.execution_token if control is not None else None

    assert task_status == "running"
    assert job_status == "running"
    assert ingest_status == "running"
    assert media_prep_status == "pending"
    assert execution_token == "token-new"


def test_worker_asr_cancel_during_transcribe_finishes_cancelled(backend_env, monkeypatch, tmp_path) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1asrcancel001")
    data_dir = Path(backend_env["data_dir"])
    _prepare_asr_input_audio(data_dir, task_id)
    state_dir = tmp_path / "asr-cancel-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    script_path = tmp_path / "graceful_asr_child.py"
    script_path.write_text(
        """#!/usr/bin/env python3
import json
import os
import signal
import sys
import time
from pathlib import Path

state_dir = Path(os.environ[\"NYARU_ASR_CANCEL_STATE_DIR\"])
state_dir.mkdir(parents=True, exist_ok=True)
(state_dir / \"pid.txt\").write_text(str(os.getpid()), encoding=\"utf-8\")

def _handle_term(signum, frame):
    (state_dir / \"term.txt\").write_text(\"received\", encoding=\"utf-8\")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, _handle_term)
sys.stdout.write(json.dumps({
    \"event\": \"phase_start\",
    \"phase\": \"transcribe\",
    \"phase_index\": 3,
    \"phase_count\": 5,
    \"message\": \"starting transcribe\",
    \"ts\": \"2026-05-03T06:30:00Z\",
}) + \"\\n\")
sys.stdout.flush()
while True:
    sys.stdout.write(json.dumps({
        \"event\": \"heartbeat\",
        \"phase\": \"transcribe\",
        \"phase_index\": 3,
        \"phase_count\": 5,
        \"elapsed_ms\": 250,
        \"message\": \"transcribe running\",
        \"ts\": \"2026-05-03T06:30:01Z\",
    }) + \"\\n\")
    sys.stdout.flush()
    time.sleep(0.1)
""",
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    monkeypatch.setenv("NYARU_ASR_CANCEL_STATE_DIR", str(state_dir))

    from app.db import session_scope
    from app.models import Task, TaskExecutionControl, TaskExecutionProgress, TaskJob, TaskStage
    from app.services.task_control import request_cancel
    from app.worker import run_worker_iteration
    import app.services.task_runner as task_runner

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "pending"
        session.add(task)

        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        job.stage_name = "asr"
        job.status = "pending"
        job.started_at = None
        job.finished_at = None
        session.add(job)

        stages = {
            stage.name: stage
            for stage in session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
        }
        for stage_name in ["ingest", "media_prep"]:
            stages[stage_name].status = "success"
            session.add(stages[stage_name])
        stages["asr"].status = "pending"
        stages["asr"].summary = None
        session.add(stages["asr"])

    monkeypatch.setattr(
        task_runner,
        "build_asr_child_command",
        lambda current_task_id, chunk_index: [str(script_path), current_task_id, str(chunk_index)],
    )
    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {
            **task_runner.STAGE_EXECUTORS,
            "translation": lambda session, current_task_id: None,
            "highlight": lambda session, current_task_id: None,
            "export": lambda session, current_task_id: None,
            "report": lambda session, current_task_id: None,
        },
    )

    result_holder: dict[str, object] = {}

    def _target() -> None:
        result_holder["claimed"] = run_worker_iteration()

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        with session_scope() as session:
            progress = session.get(TaskExecutionProgress, task_id)
            control = session.get(TaskExecutionControl, task_id)
            if (
                progress is not None
                and progress.current_phase == "transcribe"
                and control is not None
                and control.active_process_group_id is not None
            ):
                break
        time.sleep(0.05)
    else:  # pragma: no cover - defensive timeout
        raise AssertionError("Timed out waiting for active ASR transcribe phase")

    with session_scope() as session:
        request_cancel(session, task_id=task_id)

    thread.join(timeout=10)
    assert not thread.is_alive()
    assert result_holder.get("claimed") is not None
    assert (state_dir / "term.txt").read_text(encoding="utf-8") == "received"

    with session_scope() as session:
        task = session.get(Task, task_id)
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        asr_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        control = session.get(TaskExecutionControl, task_id)
        progress = session.get(TaskExecutionProgress, task_id)
        assert task is not None
        assert control is not None
        task_status = task.status
        job_status = job.status
        asr_status = asr_stage.status
        execution_token = control.execution_token
        active_process_group_id = control.active_process_group_id

    assert task_status == "cancelled"
    assert job_status == "cancelled"
    assert asr_status == "cancelled"
    assert execution_token is None
    assert active_process_group_id is None
    assert progress is None


def test_asr_stage_runs_via_child_and_parent_publishes_results(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1asrchild001")
    data_dir = Path(backend_env["data_dir"])
    audio_path = _prepare_asr_input_audio(data_dir, task_id)
    artifact_paths = _write_asr_success_outputs(data_dir, task_id)
    manifest_path = (
        data_dir / "tasks" / task_id / "work" / "asr-chunks" / "chunk-0000" / "asr-result.json"
    )
    manifest_payload = json.dumps(
        {
            "status": "success",
            "elapsed_ms_total": 2500,
            "phases": [
                {"name": "model_load", "status": "success", "elapsed_ms": 250},
                {"name": "vad", "status": "success", "elapsed_ms": 250},
                {"name": "transcribe", "status": "success", "elapsed_ms": 1000},
                {"name": "align", "status": "success", "elapsed_ms": 500},
                {"name": "persist", "status": "success", "elapsed_ms": 500},
            ],
            "artifacts": {
                "audio_path": str(audio_path),
                "transcript_path": str(artifact_paths["transcript_path"]),
                "subtitle_path": str(artifact_paths["subtitle_path"]),
                "raw_alignment_path": str(artifact_paths["raw_alignment_path"]),
            },
            "model_metadata": {
                "provider": "whisperx",
                "model_name": "large-v3",
                "alignment_model_name": None,
                "device": "cpu",
                "compute_type": "int8",
                "language": "zh",
                "batch_size": 8,
            },
            "error": None,
        },
        ensure_ascii=False,
    )

    from app.db import session_scope
    from app.models import Artifact, TaskExecutionProgress, TaskStage
    from app.services.pipeline_support import StructuredProcessGroupResult
    import app.services.task_runner as task_runner

    executor = getattr(task_runner, "_execute_asr_subprocess", None)
    assert executor is not None

    downstream_calls: list[str] = []
    observed_progress: list[tuple[str, str | None]] = []

    def _downstream(stage_name: str):
        def _handler(session, current_task_id: str) -> None:
            assert current_task_id == task_id
            downstream_calls.append(stage_name)

        return _handler

    def _fake_run_structured_child(session, *, task_id: str, args, log_path, on_event=None, **kwargs):
        assert args[-2:] == [task_id, "0"]
        manifest_path.write_text(manifest_payload, encoding="utf-8")
        phase_start = {
            "event": "phase_start",
            "phase": "model_load",
            "phase_index": 1,
            "phase_count": 5,
            "message": "starting model_load",
            "ts": "2026-05-03T06:10:00Z",
        }
        heartbeat = {
            "event": "heartbeat",
            "phase": "model_load",
            "phase_index": 1,
            "phase_count": 5,
            "elapsed_ms": 125,
            "message": "model_load running",
            "ts": "2026-05-03T06:10:01Z",
        }
        phase_complete = {
            "event": "phase_complete",
            "phase": "model_load",
            "phase_index": 1,
            "phase_count": 5,
            "elapsed_ms": 250,
            "ts": "2026-05-03T06:10:02Z",
        }
        success = {
            "event": "success",
            "phase": "persist",
            "elapsed_ms_total": 2500,
            "manifest_path": str(manifest_path),
            "ts": "2026-05-03T06:10:03Z",
        }
        for event in [phase_start, heartbeat, phase_complete, success]:
            if on_event is not None:
                on_event(event)
            if event["event"] == "heartbeat":
                progress = session.get(TaskExecutionProgress, task_id)
                assert progress is not None
                observed_progress.append((progress.current_phase, progress.latest_message))
        progress = session.get(TaskExecutionProgress, task_id)
        assert progress is not None
        return StructuredProcessGroupResult(
            completed_process=subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr=""),
            events=[phase_start, heartbeat, phase_complete, success],
            latest_event=success,
        )

    monkeypatch.setattr(
        task_runner,
        "run_tracked_structured_process_group_command",
        _fake_run_structured_child,
        raising=False,
    )
    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {
            **task_runner.STAGE_EXECUTORS,
            "asr": executor,
            "translation": _downstream("translation"),
            "highlight": _downstream("highlight"),
            "export": _downstream("export"),
            "report": _downstream("report"),
        },
    )

    with session_scope() as session:
        result = task_runner.run_task_pipeline(session, task_id, start_stage_name="asr")

    assert result.final_status == "success"
    assert result.completed_stages == ["asr", "translation", "highlight", "export", "report"]
    assert downstream_calls == ["translation", "highlight", "export", "report"]
    assert observed_progress == [("model_load", "model_load running")]

    with session_scope() as session:
        asr_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "asr")
        ).all()
        execution_progress = session.get(TaskExecutionProgress, task_id)
        asr_stage_status = asr_stage.status
        asr_stage_summary = asr_stage.summary
        artifact_kinds = {artifact.kind for artifact in artifacts}

    assert asr_stage_status == "success"
    assert asr_stage_summary == "Generated aligned transcript and Chinese subtitles"
    assert artifact_kinds == {"alignment_raw", "subtitle_srt", "transcript_json"}
    assert execution_progress is None


def test_asr_child_crash_does_not_leave_parent_half_updated(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1asrchild002")
    data_dir = Path(backend_env["data_dir"])
    _prepare_asr_input_audio(data_dir, task_id)

    from app.db import session_scope
    from app.models import Artifact, TaskExecutionProgress, TaskJob, TaskStage
    from app.services.pipeline_support import StructuredProcessGroupResult
    import app.services.task_runner as task_runner

    executor = getattr(task_runner, "_execute_asr_subprocess", None)
    assert executor is not None

    phase_start = {
        "event": "phase_start",
        "phase": "model_load",
        "phase_index": 1,
        "phase_count": 5,
        "message": "starting model_load",
        "ts": "2026-05-03T06:20:00Z",
    }

    def _fake_run_structured_child(session, *, task_id: str, args, log_path, on_event=None, **kwargs):
        if on_event is not None:
            on_event(phase_start)
            progress = session.get(TaskExecutionProgress, task_id)
            assert progress is not None
            assert progress.current_phase == "model_load"
        return StructuredProcessGroupResult(
            completed_process=subprocess.CompletedProcess(args=args, returncode=9, stdout="", stderr="child crashed"),
            events=[phase_start],
            latest_event=phase_start,
        )

    monkeypatch.setattr(
        task_runner,
        "run_tracked_structured_process_group_command",
        _fake_run_structured_child,
        raising=False,
    )
    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {
            **task_runner.STAGE_EXECUTORS,
            "asr": executor,
            "translation": lambda session, current_task_id: None,
        },
    )

    with pytest.raises(Exception):
        with session_scope() as session:
            task_runner.run_task_pipeline(session, task_id, start_stage_name="asr")

    with session_scope() as session:
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        asr_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        downstream_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "translation")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "asr")
        ).all()
        execution_progress = session.get(TaskExecutionProgress, task_id)
        job_status = job.status
        job_stage_name = job.stage_name
        asr_stage_status = asr_stage.status
        downstream_stage_status = downstream_stage.status

    assert job_status == "failed"
    assert job_stage_name == "asr"
    assert asr_stage_status == "failed"
    assert downstream_stage_status == "pending"
    assert artifacts == []
    assert execution_progress is None


def test_worker_asr_malformed_child_event_fails_without_lingering_progress_or_running_state(
    backend_env, monkeypatch, tmp_path
) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1asrmalformed001")
    data_dir = Path(backend_env["data_dir"])
    _prepare_asr_input_audio(data_dir, task_id)
    script_path = tmp_path / "malformed_asr_child.py"
    script_path.write_text(
        """#!/usr/bin/env python3
import time

print("not-json", flush=True)
while True:
    time.sleep(0.1)
""",
        encoding="utf-8",
    )
    script_path.chmod(0o755)

    from app.db import session_scope
    from app.models import Task, TaskExecutionControl, TaskExecutionProgress, TaskJob, TaskStage
    from app.repositories.tasks import get_task_detail
    from app.worker import run_worker_iteration
    import app.services.task_runner as task_runner

    with session_scope() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "pending"
        session.add(task)

        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        job.stage_name = "asr"
        job.status = "pending"
        job.started_at = None
        job.finished_at = None
        session.add(job)

        stages = {
            stage.name: stage
            for stage in session.exec(select(TaskStage).where(TaskStage.task_id == task_id)).all()
        }
        for stage_name in ["ingest", "media_prep"]:
            stages[stage_name].status = "success"
            session.add(stages[stage_name])
        stages["asr"].status = "pending"
        stages["asr"].summary = None
        session.add(stages["asr"])

    monkeypatch.setattr(
        task_runner,
        "build_asr_child_command",
        lambda current_task_id, chunk_index: [str(script_path), current_task_id, str(chunk_index)],
    )
    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {
            **task_runner.STAGE_EXECUTORS,
            "translation": lambda session, current_task_id: None,
            "highlight": lambda session, current_task_id: None,
            "export": lambda session, current_task_id: None,
            "report": lambda session, current_task_id: None,
        },
    )

    result_holder: dict[str, object] = {}

    def _target() -> None:
        try:
            result_holder["claimed"] = run_worker_iteration()
        except BaseException as exc:  # pragma: no cover - asserted below
            result_holder["exception"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=10)

    assert not thread.is_alive()
    exception = result_holder.get("exception")
    assert exception is not None
    assert getattr(exception, "code", None) == "malformed_progress_event"

    with session_scope() as session:
        task = session.get(Task, task_id)
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).one()
        asr_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        translation_stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "translation")
        ).one()
        control = session.get(TaskExecutionControl, task_id)
        execution_progress = session.get(TaskExecutionProgress, task_id)
        detail = get_task_detail(session, task_id)
        assert task is not None
        assert control is not None
        assert detail is not None

        assert task.status == "failed"
        assert job.status == "failed"
        assert job.stage_name == "asr"
        assert asr_stage.status == "failed"
        assert asr_stage.summary == "malformed_progress_event"
        assert translation_stage.status == "pending"
        assert control.execution_token is None
        assert control.active_process_group_id is None
        assert control.cancel_requested is False
        assert control.force_kill_requested is False
        assert execution_progress is None
        assert detail.get("status") == "failed"
        assert "execution_progress" not in detail
