from __future__ import annotations

import json
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
    perf_values = iter([100.0, 101.5])
    monkeypatch.setattr("app.services.asr_whisperx.time.perf_counter", lambda: next(perf_values))

    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.asr_whisperx import transcribe_task_audio

    with session_scope() as session:
        result = transcribe_task_audio(session, task_id)

    assert result.audio_path == audio_path
    assert result.transcript_path.exists()
    assert result.subtitle_path.exists()
    assert result.raw_alignment_path.exists()
    assert result.elapsed_seconds == 1.5
    assert result.model_metadata["provider"] == "whisperx"
    assert result.model_metadata["model_name"] == "large-v3"

    transcript_payload = json.loads(result.transcript_path.read_text(encoding="utf-8"))
    assert [segment["id"] for segment in transcript_payload["segments"]] == ["seg-0001", "seg-0002"]
    assert transcript_payload["segments"][0]["words"][0]["text"] == "你好"
    assert transcript_payload["elapsed_seconds"] == 1.5

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
    assert transcript_metadata["elapsed_seconds"] == 1.5


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
