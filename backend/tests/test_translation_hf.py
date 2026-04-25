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
    monkeypatch.setenv("APP_TRANSLATION_PROVIDER", "hf")
    monkeypatch.setenv("APP_TRANSLATION_MODEL_NAME", "facebook/nllb-200-distilled-600M")
    monkeypatch.setenv("APP_TRANSLATION_DEVICE", "cpu")
    monkeypatch.setenv("APP_TRANSLATION_SOURCE_LANGUAGE_CODE", "zho_Hans")
    monkeypatch.setenv("APP_TRANSLATION_TARGET_LANGUAGE_CODE", "jpn_Jpan")
    _reset_runtime_state()
    return {"data_dir": data_dir, "db_path": db_path}


def _create_task(source_url: str) -> str:
    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, source_url)
        return payload["task_id"]


def _prepare_asr_fixture(data_dir: Path, task_id: str) -> Path:
    transcript_path = data_dir / "tasks" / task_id / "work" / "asr-segments.json"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        json.dumps(
            {
                "elapsed_seconds": 1.2,
                "model_metadata": {"provider": "whisperx", "model_name": "large-v3"},
                "segment_count": 2,
                "segments": [
                    {
                        "id": "seg-0001",
                        "start_seconds": 0.0,
                        "end_seconds": 1.4,
                        "text": "你好",
                        "words": None,
                    },
                    {
                        "id": "seg-0002",
                        "start_seconds": 1.4,
                        "end_seconds": 3.0,
                        "text": "世界",
                        "words": None,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return transcript_path


class _FakeProvider:
    metadata = {
        "provider": "hf",
        "model_name": "facebook/nllb-200-distilled-600M",
        "source_language_code": "zho_Hans",
        "target_language_code": "jpn_Jpan",
        "device": "cpu",
    }

    def __init__(self, translated_texts: list[str]):
        self.translated_texts = translated_texts

    def translate_segments(self, segments):
        assert [segment.id for segment in segments] == ["seg-0001", "seg-0002"]
        return list(self.translated_texts)


class _ExplodingProvider:
    metadata = {
        "provider": "hf",
        "model_name": "facebook/nllb-200-distilled-600M",
        "source_language_code": "zho_Hans",
        "target_language_code": "jpn_Jpan",
        "device": "cpu",
    }

    def translate_segments(self, segments):
        raise RuntimeError("translation backend crashed")


class _FakeInferenceMode:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeTensor:
    def __init__(self, value: str):
        self.value = value
        self.moved_to: list[str] = []

    def to(self, device: str):
        self.moved_to.append(device)
        return self


class _FakeTokenizer:
    def __init__(self):
        self.src_lang = None
        self.lang_code_to_id = {"jpn_Jpan": 7}
        self.calls: list[str] = []

    def __call__(self, text: str, *, return_tensors: str):
        assert return_tensors == "pt"
        self.calls.append(text)
        return {
            "input_ids": _FakeTensor(text),
            "attention_mask": _FakeTensor("mask"),
        }

    def batch_decode(self, generated_tokens, *, skip_special_tokens: bool):
        assert skip_special_tokens is True
        return [generated_tokens[0]]


class _FakeModel:
    def __init__(self):
        self.devices: list[str] = []
        self.generate_calls: list[dict] = []

    def to(self, device: str):
        self.devices.append(device)
        return self

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return ["こんにちは"]


class _FakeAutoTokenizer:
    last_instance: _FakeTokenizer | None = None

    @classmethod
    def from_pretrained(cls, model_name: str):
        assert model_name == "facebook/nllb-200-distilled-600M"
        cls.last_instance = _FakeTokenizer()
        return cls.last_instance


class _FakeAutoModelForSeq2SeqLM:
    last_instance: _FakeModel | None = None

    @classmethod
    def from_pretrained(cls, model_name: str):
        assert model_name == "facebook/nllb-200-distilled-600M"
        cls.last_instance = _FakeModel()
        return cls.last_instance


class _FakeTransformersModule:
    AutoTokenizer = _FakeAutoTokenizer
    AutoModelForSeq2SeqLM = _FakeAutoModelForSeq2SeqLM


class _FakeTorchModule:
    @staticmethod
    def inference_mode():
        return _FakeInferenceMode()


def test_translate_segments_preserves_ids_timestamps_and_writes_bilingual_outputs(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1es411c7mV")
    _prepare_asr_fixture(Path(backend_env["data_dir"]), task_id)

    monkeypatch.setattr(
        "app.services.translation_provider.build_translation_provider",
        lambda settings=None: _FakeProvider(["こんにちは", "世界"]),
    )
    perf_values = iter([10.0, 12.25])
    monkeypatch.setattr("app.services.translation_provider.time.perf_counter", lambda: next(perf_values))

    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.translation_provider import translate_task_subtitles

    with session_scope() as session:
        result = translate_task_subtitles(session, task_id)

    transcript_payload = json.loads(result.transcript_path.read_text(encoding="utf-8"))
    assert result.elapsed_seconds == 2.25
    assert transcript_payload["segments"][0]["id"] == "seg-0001"
    assert transcript_payload["segments"][0]["start_seconds"] == 0.0
    assert transcript_payload["segments"][0]["end_seconds"] == 1.4
    assert transcript_payload["segments"][0]["text"] == "你好"
    assert transcript_payload["segments"][0]["translated_text"] == "こんにちは"
    assert result.subtitle_path.read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:00:01,400\n"
        "你好\n"
        "こんにちは\n\n"
        "2\n"
        "00:00:01,400 --> 00:00:03,000\n"
        "世界\n"
        "世界\n"
    )

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "translation")
        ).one()
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "translation")
        ).all()
        stage_status = stage.status
        stage_summary = stage.summary
        artifact_kinds = {artifact.kind for artifact in artifacts}

    assert stage_status == "success"
    assert stage_summary == "Generated bilingual Chinese/Japanese subtitles"
    assert artifact_kinds == {"bilingual_subtitle_srt", "bilingual_transcript_json"}


def test_hf_provider_uses_lazy_transformer_loader_and_language_codes(monkeypatch) -> None:
    monkeypatch.setattr("app.services.translation_hf._load_transformers_module", lambda: _FakeTransformersModule())
    monkeypatch.setattr("app.services.translation_hf._load_torch_module", lambda: _FakeTorchModule())

    from app.services.subtitles import SubtitleSegment
    from app.services.translation_hf import HuggingFaceTranslationProvider

    provider = HuggingFaceTranslationProvider(
        model_name="facebook/nllb-200-distilled-600M",
        device="cpu",
        source_language_code="zho_Hans",
        target_language_code="jpn_Jpan",
    )

    translated_texts = provider.translate_segments(
        [SubtitleSegment(id="seg-0001", start_seconds=0.0, end_seconds=1.0, text="你好", words=None)]
    )

    assert translated_texts == ["こんにちは"]
    assert _FakeAutoTokenizer.last_instance is not None
    assert _FakeAutoTokenizer.last_instance.src_lang == "zho_Hans"
    assert _FakeAutoModelForSeq2SeqLM.last_instance is not None
    assert _FakeAutoModelForSeq2SeqLM.last_instance.devices == ["cpu"]
    assert _FakeAutoModelForSeq2SeqLM.last_instance.generate_calls[0]["forced_bos_token_id"] == 7


def test_translation_runtime_failure_marks_stage_failed(backend_env, monkeypatch) -> None:
    task_id = _create_task("https://www.bilibili.com/video/BV1fs411c7mW")
    transcript_path = _prepare_asr_fixture(Path(backend_env["data_dir"]), task_id)

    monkeypatch.setattr(
        "app.services.translation_provider.build_translation_provider",
        lambda settings=None: _ExplodingProvider(),
    )

    from app.db import session_scope
    from app.models import Task, TaskStage
    from app.services.translation_provider import TranslationFailure, translate_task_subtitles

    with pytest.raises(TranslationFailure) as exc_info:
        with session_scope() as session:
            translate_task_subtitles(session, task_id)

    assert exc_info.value.code == "translation_failed"
    assert "facebook/nllb-200-distilled-600M" in str(exc_info.value)
    assert transcript_path.exists()

    with session_scope() as session:
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "translation")
        ).one()
        task = session.get(Task, task_id)
        stage_status = stage.status
        stage_summary = stage.summary
        task_status = task.status if task is not None else None

    assert stage_status == "failed"
    assert stage_summary == "translation_failed"
    assert task_status == "failed"
