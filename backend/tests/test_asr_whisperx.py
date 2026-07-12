from __future__ import annotations

import json
import sys
import time
import types
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
    monkeypatch.setenv("APP_WHISPERX_MODEL_NAME", "large-v3")
    monkeypatch.setenv("APP_WHISPERX_LANGUAGE", "zh")
    monkeypatch.setenv("APP_WHISPERX_DEVICE", "cpu")
    monkeypatch.setenv("APP_WHISPERX_COMPUTE_TYPE", "int8")
    _reset_runtime_state()
    return {"data_dir": data_dir, "db_path": db_path}


@pytest.fixture(autouse=True)
def task_control_shim(monkeypatch):
    shim = types.ModuleType("app.services.task_control")
    shim.ensure_current_execution_context = lambda session, *, task_id: None
    monkeypatch.setitem(sys.modules, "app.services.task_control", shim)
    yield


def _create_task(source_url: str) -> str:
    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, source_url)
        return payload["task_id"]


def _prepare_audio_fixture(data_dir: Path, task_id: str) -> Path:
    audio_path = data_dir / "tasks" / task_id / "work" / "asr-input.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"RIFFfixture")
    return audio_path


class _FakeModel:
    def __init__(self, transcription_result: dict):
        self.transcription_result = transcription_result

    def transcribe(self, audio_path: str, *, batch_size: int, language: str) -> dict:
        assert audio_path.endswith("asr-input.wav")
        assert batch_size >= 1
        return {
            **self.transcription_result,
            "language": language,
        }


class _FakeWhisperX:
    def __init__(self, *, transcription_result: dict, aligned_result: dict):
        self.transcription_result = transcription_result
        self.aligned_result = aligned_result

    def load_model(self, model_name: str, device: str, *, compute_type: str, download_root: str | None = None):
        assert model_name == "large-v3"
        assert device == "cpu"
        assert compute_type == "int8"
        return _FakeModel(self.transcription_result)

    def load_align_model(
        self,
        *,
        language_code: str,
        device: str,
        model_name: str | None = None,
        model_dir: str | None = None,
        model_cache_only: bool = False,
    ):
        assert language_code == "zh"
        assert device == "cpu"
        assert model_cache_only is False
        return object(), {"language_code": language_code, "align_model_name": model_name or "default-align"}

    def align(
        self,
        segments: list[dict],
        align_model,
        metadata: dict,
        audio_path: str,
        device: str,
        *,
        return_char_alignments: bool,
    ) -> dict:
        assert segments == self.transcription_result["segments"]
        assert audio_path.endswith("asr-input.wav")
        assert metadata["language_code"] == "zh"
        assert device == "cpu"
        assert return_char_alignments is False
        return self.aligned_result


def test_transcribe_fixture_audio_persists_alignment_json_and_srt(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1as411c7mR")
    audio_path = _prepare_audio_fixture(Path(backend_env["data_dir"]), task_id)
    fake_whisperx = _FakeWhisperX(
        transcription_result={
            "segments": [
                {"start": 0.0, "end": 1.2, "text": " 你好 ", "words": [{"word": "你好", "start": 0.0, "end": 1.2}]},
                {"start": 1.2, "end": 2.8, "text": "世界", "words": []},
            ]
        },
        aligned_result={
            "segments": [
                {"start": 0.0, "end": 1.2, "text": "你好", "words": [{"word": "你好", "start": 0.0, "end": 1.2, "score": 0.95}]},
                {"start": 1.2, "end": 2.8, "text": "世界", "words": []},
            ],
            "language": "zh",
        },
    )

    monkeypatch.setattr("app.services.asr_whisperx._load_whisperx_module", lambda: fake_whisperx)
    clock = {"value": 100.0}

    def _fake_perf_counter() -> float:
        clock["value"] += 0.25
        return clock["value"]

    monkeypatch.setattr("app.services.asr_whisperx.time.perf_counter", _fake_perf_counter)

    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.asr_whisperx import transcribe_task_audio

    with session_scope() as session:
        result = transcribe_task_audio(session, task_id)

    assert result.audio_path == audio_path
    assert result.transcript_path.exists()
    assert result.subtitle_path.exists()
    assert result.raw_alignment_path.exists()
    assert result.elapsed_seconds > 0
    assert result.model_metadata["provider"] == "whisperx"
    assert result.model_metadata["model_name"] == "large-v3"

    transcript_payload = json.loads(result.transcript_path.read_text(encoding="utf-8"))
    assert [segment["id"] for segment in transcript_payload["segments"]] == ["seg-0001", "seg-0002"]
    assert transcript_payload["segments"][0]["words"][0]["text"] == "你好"
    assert transcript_payload["elapsed_seconds"] == result.elapsed_seconds

    assert result.subtitle_path.read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:00:01,200\n"
        "你好\n\n"
        "2\n"
        "00:00:01,200 --> 00:00:02,800\n"
        "世界\n"
    )
    assert json.loads(result.raw_alignment_path.read_text(encoding="utf-8"))["language"] == "zh"

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "asr")
        ).all()
        stage_status = stage.status
        stage_summary = stage.summary
        artifact_kinds = {artifact.kind for artifact in artifacts}
        transcript_artifact = next(artifact for artifact in artifacts if artifact.kind == "transcript_json")
        transcript_metadata = json.loads(transcript_artifact.metadata_json)

    assert stage_status == "success"
    assert stage_summary == "Generated aligned transcript and Chinese subtitles"
    assert artifact_kinds == {"alignment_raw", "subtitle_srt", "transcript_json"}
    assert transcript_metadata["elapsed_seconds"] == result.elapsed_seconds


def test_missing_model_is_terminal(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1bs411c7mS")
    _prepare_audio_fixture(Path(backend_env["data_dir"]), task_id)

    class _MissingModelWhisperX:
        def load_model(self, *args, **kwargs):
            raise FileNotFoundError("missing model files")

    monkeypatch.setattr("app.services.asr_whisperx._load_whisperx_module", lambda: _MissingModelWhisperX())

    from app.db import session_scope
    from app.models import Task, TaskStage
    from app.services.asr_whisperx import AsrFailure, transcribe_task_audio

    with pytest.raises(AsrFailure) as exc_info:
        with session_scope() as session:
            transcribe_task_audio(session, task_id)

    assert exc_info.value.code == "missing_model"
    assert "provision" in str(exc_info.value).lower()

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        task = session.get(Task, task_id)
        stage_status = stage.status
        stage_summary = stage.summary
        task_status = task.status if task is not None else None

    assert stage_status == "failed"
    assert stage_summary == "missing_model"
    assert task_status == "failed"


def test_oom_is_classified(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1cs411c7mT")
    _prepare_audio_fixture(Path(backend_env["data_dir"]), task_id)

    class _OomWhisperX:
        def load_model(self, *args, **kwargs):
            raise RuntimeError("CUDA out of memory while loading model")

    monkeypatch.setattr("app.services.asr_whisperx._load_whisperx_module", lambda: _OomWhisperX())

    from app.db import session_scope
    from app.models import TaskStage
    from app.services.asr_whisperx import AsrFailure, transcribe_task_audio

    with pytest.raises(AsrFailure) as exc_info:
        with session_scope() as session:
            transcribe_task_audio(session, task_id)

    assert exc_info.value.code == "oom"

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        stage_status = stage.status
        stage_summary = stage.summary

    assert stage_status == "failed"
    assert stage_summary == "oom"


def test_rocm_cuda_request_falls_back_to_cpu_float32(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1rocmfallback001")
    _prepare_audio_fixture(Path(backend_env["data_dir"]), task_id)
    monkeypatch.setenv("APP_WHISPERX_DEVICE", "cuda")
    monkeypatch.setenv("APP_WHISPERX_COMPUTE_TYPE", "float16")

    observed: dict[str, object] = {}

    class _FallbackWhisperX(_FakeWhisperX):
        def load_model(self, model_name: str, device: str, *, compute_type: str, download_root: str | None = None):
            observed["load_model_device"] = device
            observed["load_model_compute_type"] = compute_type
            return _FakeModel(self.transcription_result)

        def load_align_model(
            self,
            *,
            language_code: str,
            device: str,
            model_name: str | None = None,
            model_dir: str | None = None,
            model_cache_only: bool = False,
        ):
            observed["align_device"] = device
            return super().load_align_model(
                language_code=language_code,
                device=device,
                model_name=model_name,
                model_dir=model_dir,
                model_cache_only=model_cache_only,
            )

    fake_whisperx = _FallbackWhisperX(
        transcription_result={"segments": [{"start": 0.0, "end": 1.0, "text": "你好"}]},
        aligned_result={"segments": [{"start": 0.0, "end": 1.0, "text": "你好", "words": []}]},
    )

    class _FakeCTranslate2:
        @staticmethod
        def get_supported_compute_types(device: str):
            if device == "cuda":
                raise RuntimeError("CUDA failed with error CUDA driver version is insufficient for CUDA runtime version")
            assert device == "cpu"
            return {"float32", "int8", "int8_float32"}

    monkeypatch.setattr("app.services.asr_whisperx._load_whisperx_module", lambda: fake_whisperx)
    monkeypatch.setattr("app.services.asr_whisperx._load_ctranslate2_module", lambda: _FakeCTranslate2())
    monkeypatch.setattr(
        "app.services.asr_whisperx.detect_runtime_profile",
        lambda: {
            "detected_profile": "wsl-rocm",
            "accelerator": {"torch_build_family": "rocm"},
            "platform": {"is_wsl": True},
        },
    )

    from app.db import session_scope
    from app.services.asr_whisperx import transcribe_task_audio

    with session_scope() as session:
        result = transcribe_task_audio(session, task_id)

    assert observed == {
        "load_model_device": "cpu",
        "load_model_compute_type": "float32",
        "align_device": "cpu",
    }
    assert result.model_metadata["device"] == "cpu"
    assert result.model_metadata["compute_type"] == "float32"
    assert result.model_metadata["requested_device"] == "cuda"
    assert result.model_metadata["requested_compute_type"] == "float16"
    assert "runtime_warning" in result.model_metadata


def test_alignment_failure_is_classified(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1ds411c7mU")
    _prepare_audio_fixture(Path(backend_env["data_dir"]), task_id)
    fake_whisperx = _FakeWhisperX(
        transcription_result={"segments": [{"start": 0.0, "end": 1.0, "text": "你好"}]},
        aligned_result={"segments": [{"text": "missing timestamps"}]},
    )

    monkeypatch.setattr("app.services.asr_whisperx._load_whisperx_module", lambda: fake_whisperx)

    from app.db import session_scope
    from app.models import TaskStage
    from app.services.asr_whisperx import AsrFailure, transcribe_task_audio

    with pytest.raises(AsrFailure) as exc_info:
        with session_scope() as session:
            transcribe_task_audio(session, task_id)

    assert exc_info.value.code == "alignment_failed"

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "asr")
        ).one()
        stage_status = stage.status
        stage_summary = stage.summary

    assert stage_status == "failed"
    assert stage_summary == "alignment_failed"


def test_missing_model_recovery_payload_describes_main_and_alignment_targets(
    backend_env,
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_WHISPERX_MODEL_NAME", "large-v3")
    monkeypatch.setenv(
        "APP_WHISPERX_ALIGNMENT_MODEL_NAME",
        "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
    )
    monkeypatch.setenv("APP_WHISPERX_MODEL_CACHE_DIR", str(Path(backend_env["data_dir"]) / "models" / "whisperx"))

    from app.services.asr_whisperx import build_asr_missing_model_recovery
    from app.settings import get_settings

    recovery = build_asr_missing_model_recovery(get_settings())

    assert recovery["stage"] == "asr"
    assert recovery["kind"] == "missing_model"
    assert [model["key"] for model in recovery["models"]] == ["whisperx", "alignment"]
    assert all(model["target_dir"] for model in recovery["models"])
    assert all(model["download_supported"] is True for model in recovery["models"])


def test_download_asr_missing_models_downloads_only_requested_missing_assets(
    backend_env,
    monkeypatch,
) -> None:
    model_root = Path(backend_env["data_dir"]) / "models"
    monkeypatch.setenv("APP_WHISPERX_MODEL_CACHE_DIR", str(model_root / "whisperx"))

    snapshot_calls: list[tuple[str, str]] = []
    faster_whisper_calls: list[tuple[str, str]] = []

    def fake_download_snapshot(*, repo_id: str, local_dir: str, **kwargs):
        snapshot_calls.append((repo_id, local_dir))
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "config.json").write_text("{}", encoding="utf-8")
        return local_dir

    def fake_download_faster_whisper_model(model_ref: str, output_dir: str, **kwargs):
        faster_whisper_calls.append((model_ref, output_dir))
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "config.json").write_text("{}", encoding="utf-8")
        (Path(output_dir) / "model.bin").write_bytes(b"fixture")
        return output_dir

    monkeypatch.setattr("app.services.asr_whisperx.snapshot_download", fake_download_snapshot)
    monkeypatch.setattr(
        "app.services.asr_whisperx.download_faster_whisper_model",
        fake_download_faster_whisper_model,
    )

    from app.services.asr_whisperx import download_asr_missing_models
    from app.settings import get_settings

    result = download_asr_missing_models(
        get_settings(),
        requested_keys=["whisperx", "alignment"],
    )

    assert [item["key"] for item in result["models"]] == ["whisperx", "alignment"]
    assert faster_whisper_calls == [
        ("large-v3", str(model_root / "whisperx" / "whisperx")),
    ]
    assert snapshot_calls == [
        (
            "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
            str(model_root / "whisperx" / "alignment"),
        ),
    ]
    assert all(item["status"] == "downloaded" for item in result["models"])


def test_transcribe_uses_recovery_target_directories_when_models_are_present_locally(
    backend_env,
    monkeypatch,
) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1localsnap001")
    _prepare_audio_fixture(Path(backend_env["data_dir"]), task_id)
    model_root = Path(backend_env["data_dir"]) / "models" / "whisperx"
    main_target = model_root / "whisperx"
    alignment_target = model_root / "alignment"
    main_target.mkdir(parents=True, exist_ok=True)
    alignment_target.mkdir(parents=True, exist_ok=True)
    (main_target / "config.json").write_text("{}", encoding="utf-8")
    (main_target / "model.bin").write_bytes(b"fixture")
    (alignment_target / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("APP_WHISPERX_MODEL_CACHE_DIR", str(model_root))

    observed: dict[str, str | None] = {}

    class _LocalPathWhisperX(_FakeWhisperX):
        def load_model(self, model_name: str, device: str, *, compute_type: str, download_root: str | None = None):
            observed["main_model_name"] = model_name
            observed["main_download_root"] = download_root
            assert device == "cpu"
            assert compute_type == "int8"
            return _FakeModel(self.transcription_result)

        def load_align_model(
            self,
            *,
            language_code: str,
            device: str,
            model_name: str | None = None,
            model_dir: str | None = None,
            model_cache_only: bool = False,
        ):
            observed["align_model_name"] = model_name
            observed["align_model_dir"] = model_dir
            return super().load_align_model(
                language_code=language_code,
                device=device,
                model_name=model_name,
                model_dir=model_dir,
                model_cache_only=model_cache_only,
            )

    fake_whisperx = _LocalPathWhisperX(
        transcription_result={"segments": [{"start": 0.0, "end": 1.0, "text": "你好"}]},
        aligned_result={"segments": [{"start": 0.0, "end": 1.0, "text": "你好", "words": []}]},
    )
    monkeypatch.setattr("app.services.asr_whisperx._load_whisperx_module", lambda: fake_whisperx)

    from app.db import session_scope
    from app.services.asr_whisperx import transcribe_task_audio

    with session_scope() as session:
        transcribe_task_audio(session, task_id)

    assert observed["main_model_name"] == str(main_target)
    assert observed["align_model_name"] == str(alignment_target)
    assert observed["align_model_dir"] == str(alignment_target)


def test_child_runner_emits_success_protocol_and_manifest(backend_env, monkeypatch, capsys) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1childsuccess001")
    _prepare_audio_fixture(Path(backend_env["data_dir"]), task_id)
    fake_whisperx = _FakeWhisperX(
        transcription_result={
            "segments": [
                {"start": 0.0, "end": 1.2, "text": "你好", "words": [{"word": "你好", "start": 0.0, "end": 1.2}]},
                {"start": 1.2, "end": 2.8, "text": "世界", "words": []},
            ]
        },
        aligned_result={
            "segments": [
                {"start": 0.0, "end": 1.2, "text": "你好", "words": [{"word": "你好", "start": 0.0, "end": 1.2, "score": 0.95}]},
                {"start": 1.2, "end": 2.8, "text": "世界", "words": []},
            ],
            "language": "zh",
        },
    )

    clock = {"value": 100.0}

    def _fake_perf_counter() -> float:
        clock["value"] += 0.25
        return clock["value"]

    monkeypatch.setattr("app.services.asr_whisperx._load_whisperx_module", lambda: fake_whisperx)
    monkeypatch.setattr("app.services.asr_whisperx.time.perf_counter", _fake_perf_counter)

    from app.services.asr_child_runner import run_asr_child

    result = run_asr_child(task_id)

    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.status == "success"
    assert [event["event"] for event in events] == [
        "phase_start",
        "heartbeat",
        "phase_complete",
        "phase_start",
        "heartbeat",
        "phase_complete",
        "phase_start",
        "heartbeat",
        "phase_complete",
        "phase_start",
        "heartbeat",
        "phase_complete",
        "phase_start",
        "heartbeat",
        "phase_complete",
        "success",
    ]
    assert [event["phase"] for event in events] == [
        "model_load",
        "model_load",
        "model_load",
        "vad",
        "vad",
        "vad",
        "transcribe",
        "transcribe",
        "transcribe",
        "align",
        "align",
        "align",
        "persist",
        "persist",
        "persist",
        "persist",
    ]
    assert Path(events[-1]["manifest_path"]) == result.manifest_path

    assert list(manifest.keys()) == [
        "status",
        "elapsed_ms_total",
        "phases",
        "artifacts",
        "model_metadata",
        "error",
    ]
    assert manifest["status"] == "success"
    assert manifest["elapsed_ms_total"] > 0
    assert [phase["name"] for phase in manifest["phases"]] == ["model_load", "vad", "transcribe", "align", "persist"]
    assert all(phase["status"] == "success" for phase in manifest["phases"])
    assert manifest["artifacts"]["transcript_path"].endswith("asr-segments.json")
    assert manifest["artifacts"]["subtitle_path"].endswith("subtitles.zh.srt")
    assert manifest["artifacts"]["raw_alignment_path"].endswith("asr-alignment-raw.json")
    assert manifest["model_metadata"]["model_name"] == "large-v3"
    assert manifest["error"] is None


def test_child_runner_emits_classified_failure_protocol(backend_env, monkeypatch, capsys) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1childfailure001")
    clock = {"value": 200.0}

    def _fake_perf_counter() -> float:
        clock["value"] += 0.25
        return clock["value"]

    monkeypatch.setattr("app.services.asr_whisperx.time.perf_counter", _fake_perf_counter)

    from app.services.asr_child_runner import run_asr_child

    result = run_asr_child(task_id)

    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.status == "failed"
    assert [event["event"] for event in events] == ["failure"]
    assert events[0]["phase"] == "model_load"
    assert events[0]["code"] == "missing_input"

    assert list(manifest.keys()) == [
        "status",
        "elapsed_ms_total",
        "phases",
        "artifacts",
        "model_metadata",
        "error",
    ]
    assert manifest["status"] == "failed"
    assert manifest["error"]["code"] == "missing_input"
    assert manifest["error"]["phase"] == "model_load"
    assert [phase["status"] for phase in manifest["phases"]] == ["failed", "pending", "pending", "pending", "pending"]
    assert manifest["artifacts"]["transcript_path"] is None
    assert manifest["artifacts"]["subtitle_path"] is None
    assert manifest["artifacts"]["raw_alignment_path"] is None


def test_child_runner_rejects_noncanonical_task_id(backend_env) -> None:
    from app.services.asr_child_runner import run_asr_child

    with pytest.raises(ValueError, match="Invalid task_id"):
        run_asr_child("../escape")


def test_run_pipeline_phase_emits_ongoing_heartbeats_during_long_running_work(monkeypatch) -> None:
    observed_events: list[tuple[str, int]] = []

    class _Observer:
        def phase_start(self, phase: str, *, phase_index: int, phase_count: int, message: str) -> None:
            observed_events.append(("phase_start", 0))

        def heartbeat(
            self,
            phase: str,
            *,
            phase_index: int,
            phase_count: int,
            elapsed_ms: int,
            message: str,
        ) -> None:
            observed_events.append(("heartbeat", elapsed_ms))

        def phase_complete(self, phase: str, *, phase_index: int, phase_count: int, elapsed_ms: int) -> None:
            observed_events.append(("phase_complete", elapsed_ms))

    from app.services.asr_whisperx import AsrPhaseResult, _run_pipeline_phase

    phase_results = {"transcribe": AsrPhaseResult(name="transcribe", status="pending")}

    def _slow_action() -> str:
        time.sleep(0.35)
        return "done"

    result = _run_pipeline_phase(
        phase="transcribe",
        phase_results=phase_results,
        observer=_Observer(),
        action=_slow_action,
    )

    heartbeat_events = [event for event in observed_events if event[0] == "heartbeat"]

    assert result == "done"
    assert len(heartbeat_events) >= 2
    assert heartbeat_events[0][1] == 0
    assert any(elapsed_ms > 0 for _, elapsed_ms in heartbeat_events[1:])
