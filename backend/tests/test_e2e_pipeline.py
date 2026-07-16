from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import httpx
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


def test_worker_iteration_runs_the_canonical_pipeline_smoke_path(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/bangumi/play/ep424242")

    from app.db import session_scope
    from app.models import Task, TaskJob, TaskStage
    import app.services.task_runner as task_runner
    from app.worker import run_worker_iteration

    called: list[str] = []

    def build_handler(stage_name: str):
        def _handler(session, current_task_id: str):
            assert current_task_id == task_id
            called.append(stage_name)
            if stage_name == "ingest":
                task = session.get(Task, current_task_id)
                assert task is not None
                task.source_video_id = "BV1smoke001"
                session.add(task)
            if stage_name == "export":
                return task_runner.StageDirective(
                    status="skipped",
                    summary="Awaiting user-confirmed clip export",
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
    assert claimed.stage_name == "ingest"
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
        stage_summaries = [stage.summary for stage in stages]

    assert task_status == "success"
    assert task_source_video_id == "BV1smoke001"
    assert job_status == "success"
    assert job_stage_name == "report"
    assert stage_names == list(task_runner.CANONICAL_STAGE_ORDER)
    assert stage_statuses == ["success", "success", "success", "success", "success", "skipped", "success"]
    assert stage_attempts == [1, 1, 1, 1, 1, 1, 1]
    assert stage_summaries[5] == "Awaiting user-confirmed clip export"


def test_pipeline_runs_chunked_asr_and_fake_deepseek_before_highlight_uses_final_subtitles(
    backend_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the durable five-minute pipeline contract without media, models, or network access."""
    # Given: a task with fake ffmpeg, sequential ASR child output, and a wire-level DeepSeek fake.
    task_id = _create_task("https://www.bilibili.com/video/BV1five-minute-e2e")
    data_dir = Path(backend_env["data_dir"])
    secret = "e2e-deepseek-secret-must-not-persist"
    monkeypatch.setenv("APP_DEEPSEEK_API_KEY", secret)
    monkeypatch.setenv("APP_DEEPSEEK_MAX_SEGMENTS_PER_REQUEST", "1")

    def write_wav(path: Path, duration_seconds: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16_000)
            output.writeframes(b"\0\0" * round(duration_seconds * 16_000))

    def fake_media_command(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        match args[0]:
            case "ffprobe":
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout=json.dumps({"format": {"duration": "601.25"}, "streams": []}),
                    stderr="",
                )
            case "ffmpeg":
                write_wav(Path(args[-1]), float(args[args.index("-t") + 1]))
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
            case unexpected:
                raise AssertionError(f"unexpected media command: {unexpected}")

    monkeypatch.setattr("subprocess.run", fake_media_command)

    child_indices: list[int] = []
    child_running = False

    from app.services.pipeline_support import StructuredProcessGroupResult

    def fake_asr_child(session, *, args: list[str], on_event=None, **kwargs: object) -> StructuredProcessGroupResult:
        nonlocal child_running
        assert not child_running, "ASR chunks must not run concurrently"
        child_running = True
        try:
            chunk_index = int(args[-1])
            child_indices.append(chunk_index)
            from app.services.media_chunks import load_media_chunk_manifest
            from app.services.storage import ensure_task_dirs

            work_dir = ensure_task_dirs(task_id)["work"]
            chunk = load_media_chunk_manifest(work_dir / "media-chunks.json").chunks[chunk_index]
            chunk_dir = work_dir / "asr-chunks" / chunk.id
            chunk_dir.mkdir(parents=True, exist_ok=True)
            transcript_path = chunk_dir / "asr-segments.json"
            subtitle_path = chunk_dir / "subtitles.zh.srt"
            raw_path = chunk_dir / "asr-alignment-raw.json"
            transcript_path.write_text(
                json.dumps(
                    {
                        "segments": [
                            {
                                "id": "segment-local",
                                "start_seconds": 0.0,
                                "end_seconds": min(1.0, chunk.end_seconds - chunk.start_seconds),
                                "text": f"第{chunk_index + 1}段",
                                "words": None,
                            }
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
                        "elapsed_ms_total": 1,
                        "phases": [],
                        "artifacts": {
                            "audio_path": str(chunk.audio_path.resolve()),
                            "transcript_path": str(transcript_path.resolve()),
                            "subtitle_path": str(subtitle_path.resolve()),
                            "raw_alignment_path": str(raw_path.resolve()),
                        },
                        "model_metadata": {"provider": "fake-whisperx"},
                        "error": None,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            event = {"event": "success", "phase": "persist", "elapsed_ms_total": 1}
            if on_event is not None:
                on_event(event)
            return StructuredProcessGroupResult(
                completed_process=subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr=""),
                events=[event],
                latest_event=event,
            )
        finally:
            child_running = False

    monkeypatch.setattr("app.services.task_runner.run_tracked_structured_process_group_command", fake_asr_child)

    class FakeTranslationProvider:
        metadata = {"provider": "fake-hf", "model_name": "fake-hf-model"}

        def translate_segments(self, segments):
            return [f"翻译-{segment.id}" for segment in segments]

    def fake_deepseek_response(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requested_rows = json.loads(payload["messages"][1]["content"])["requested_rows"]
        corrections = [
            {
                **row,
                "translated_text": f"校对-{row['translated_text']}",
            }
            for row in requested_rows
        ]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"corrections": corrections}, ensure_ascii=False)}}]},
        )

    from app.services.proofread_deepseek import DeepSeekProofreader
    from app.settings import get_settings

    proofreader = DeepSeekProofreader(
        get_settings(),
        client=httpx.Client(transport=httpx.MockTransport(fake_deepseek_response)),
    )
    monkeypatch.setattr(
        "app.services.translation_provider.build_translation_provider", lambda settings=None: FakeTranslationProvider()
    )
    monkeypatch.setattr("app.services.translation_provider.build_proofreader", lambda settings: proofreader)

    import app.services.task_runner as task_runner

    def fake_ingest(session, current_task_id: str) -> None:
        source_path = data_dir / "tasks" / current_task_id / "raw" / "source.mp4"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"fake-video")

    def assert_highlight_reads_final(session, current_task_id: str) -> task_runner.StageDirective:
        from app.repositories.tasks import get_task_record
        from app.services.highlights import _resolve_transcript_path

        record = get_task_record(session, current_task_id)
        assert record is not None
        transcript_path = _resolve_transcript_path(current_task_id, record)
        assert transcript_path.name == "subtitles.zh-ja.json"
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
        assert all(row["translated_text"].startswith("校对-") for row in payload["segments"])
        return task_runner.StageDirective(status="skipped", summary="Fake highlight checked proofread subtitles")

    monkeypatch.setattr(
        task_runner,
        "STAGE_EXECUTORS",
        {
            **task_runner.STAGE_EXECUTORS,
            "ingest": fake_ingest,
            "highlight": assert_highlight_reads_final,
        },
    )

    from app.db import session_scope
    from app.models import Artifact, TaskStage

    # When: the real task runner advances through every canonical stage.
    with session_scope() as session:
        result = task_runner.run_task_pipeline(session, task_id)

    # Then: the task has source-global outputs, no concurrent child invocation, and no persisted secret.
    work_dir = data_dir / "tasks" / task_id / "work"
    merged = json.loads((work_dir / "asr-segments.json").read_text(encoding="utf-8"))
    assert result.final_status == "success"
    assert result.completed_stages == list(task_runner.CANONICAL_STAGE_ORDER)
    assert child_indices == [0, 1, 2]
    assert [(row["id"], row["start_seconds"]) for row in merged["segments"]] == [
        ("seg-000001", 0.0),
        ("seg-000002", 300.0),
        ("seg-000003", 600.0),
    ]
    with session_scope() as session:
        stages = session.exec(select(TaskStage).where(TaskStage.task_id == task_id).order_by(TaskStage.id)).all()
        artifacts = session.exec(select(Artifact).where(Artifact.task_id == task_id)).all()
        stage_names = [stage.name for stage in stages]
        stage_statuses = [stage.status for stage in stages]
        artifact_metadata = [artifact.metadata_json for artifact in artifacts]
    assert stage_names == list(task_runner.CANONICAL_STAGE_ORDER)
    assert stage_statuses == ["success", "success", "success", "success", "skipped", "skipped", "success"]
    persisted_text = "\n".join(
        artifact_metadata
        + [path.read_text(encoding="utf-8", errors="ignore") for path in (data_dir / "tasks" / task_id).rglob("*") if path.is_file()]
    )
    assert secret not in persisted_text
