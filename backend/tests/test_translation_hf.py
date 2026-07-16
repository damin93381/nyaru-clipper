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


class _PassthroughProofreader:
    """Keep non-proofreader translation tests hermetic while preserving the constrained contract."""

    def proofread_segments(self, segments):
        from app.services.proofread_deepseek import ProofreadBatchAudit, ProofreadResult

        return ProofreadResult(
            segments=list(segments),
            batch_audits=[
                ProofreadBatchAudit(
                    batch_index=0,
                    model="deepseek-test",
                    attempt_count=1,
                    elapsed_seconds=0.0,
                    changed_segment_count=0,
                    token_usage={},
                )
            ],
        )


@pytest.fixture(autouse=True)
def _stub_proofreader(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.translation_provider.build_proofreader",
        lambda settings: _PassthroughProofreader(),
    )


def _create_task(source_url: str) -> str:
    from app.db import init_db, session_scope
    from app.repositories.tasks import create_task

    init_db()
    with session_scope() as session:
        payload, _ = create_task(session, source_url)
        return payload["task_id"]


def _prepare_asr_fixture(data_dir: Path, task_id: str) -> Path:
    from app.services.media_chunks import build_media_chunk_manifest, write_media_chunk_manifest_atomically

    transcript_path = data_dir / "tasks" / task_id / "work" / "asr-segments.json"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_media_chunk_manifest(3.0, work_dir=transcript_path.parent)
    for chunk in manifest.chunks:
        chunk.audio_path.parent.mkdir(parents=True, exist_ok=True)
        chunk.audio_path.write_bytes(b"RIFFfixture")
    write_media_chunk_manifest_atomically(transcript_path.parent / "media-chunks.json", manifest)
    transcript_path.write_text(
        json.dumps(
            {
                "elapsed_seconds": 0.3,
                "model_metadata": {"provider": "whisperx", "model_name": "large-v3"},
                "segment_count": 2,
                "segments": [
                    {
                        "id": "seg-000001",
                        "start_seconds": 0.0,
                        "end_seconds": 1.4,
                        "text": "你好",
                        "words": None,
                    },
                    {
                        "id": "seg-000002",
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
    _write_verified_asr_chunk_outputs(
        work_dir=transcript_path.parent,
        manifest=manifest,
        segments=json.loads(transcript_path.read_text(encoding="utf-8"))["segments"],
    )
    return transcript_path


def _prepare_chunked_asr_fixture(data_dir: Path, task_id: str) -> Path:
    """Create three source-global ASR rows that belong to distinct media chunks."""
    from app.services.media_chunks import build_media_chunk_manifest, write_media_chunk_manifest_atomically

    work_dir = data_dir / "tasks" / task_id / "work"
    manifest = build_media_chunk_manifest(601.25, work_dir=work_dir)
    for chunk in manifest.chunks:
        chunk.audio_path.parent.mkdir(parents=True, exist_ok=True)
        chunk.audio_path.write_bytes(b"RIFFfixture")
    write_media_chunk_manifest_atomically(work_dir / "media-chunks.json", manifest)

    transcript_path = work_dir / "asr-segments.json"
    transcript_path.write_text(
        json.dumps(
            {
                "elapsed_seconds": 0.9,
                "model_metadata": {"provider": "whisperx", "model_name": "large-v3"},
                "segment_count": 3,
                "segments": [
                    {
                        "id": "seg-000001",
                        "start_seconds": 0.0,
                        "end_seconds": 1.4,
                        "text": "第一段",
                        "words": [{"text": "第一段", "start_seconds": 0.0, "end_seconds": 1.4, "confidence": 0.9}],
                    },
                    {
                        "id": "seg-000002",
                        "start_seconds": 300.0,
                        "end_seconds": 301.4,
                        "text": "第二段",
                        "words": [{"text": "第二段", "start_seconds": 300.0, "end_seconds": 301.4, "confidence": 0.8}],
                    },
                    {
                        "id": "seg-000003",
                        "start_seconds": 600.0,
                        "end_seconds": 601.0,
                        "text": "第三段",
                        "words": [{"text": "第三段", "start_seconds": 600.0, "end_seconds": 601.0, "confidence": 0.7}],
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _write_verified_asr_chunk_outputs(
        work_dir=work_dir,
        manifest=manifest,
        segments=json.loads(transcript_path.read_text(encoding="utf-8"))["segments"],
    )
    return transcript_path


def _write_verified_asr_chunk_outputs(*, work_dir: Path, manifest, segments: list[dict]) -> None:
    """Create the same durable per-chunk ASR contract produced by the ASR stage."""
    aggregate_manifest_path = work_dir / "asr-aggregate-manifest.json"
    aggregate_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "success",
                "chunk_count": len(manifest.chunks),
                "chunk_ids": [chunk.id for chunk in manifest.chunks],
                "elapsed_seconds": round(0.3 * len(manifest.chunks), 3),
                "model_metadata": {"provider": "whisperx", "model_name": "large-v3"},
                "segment_count": len(segments),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    for chunk in manifest.chunks:
        chunk_dir = work_dir / "asr-chunks" / chunk.id
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_segments: list[dict] = []
        for segment in segments:
            if not (chunk.start_seconds <= segment["start_seconds"] and segment["end_seconds"] <= chunk.end_seconds):
                continue
            local_segment = {
                **segment,
                "start_seconds": segment["start_seconds"] - chunk.start_seconds,
                "end_seconds": segment["end_seconds"] - chunk.start_seconds,
            }
            if segment.get("words") is not None:
                local_segment["words"] = [
                    {
                        **word,
                        "start_seconds": word["start_seconds"] - chunk.start_seconds,
                        "end_seconds": word["end_seconds"] - chunk.start_seconds,
                    }
                    for word in segment["words"]
                ]
            chunk_segments.append(local_segment)
        chunk_transcript_path = chunk_dir / "asr-segments.json"
        chunk_subtitle_path = chunk_dir / "subtitles.zh.srt"
        chunk_raw_alignment_path = chunk_dir / "asr-alignment-raw.json"
        chunk_transcript_path.write_text(
            json.dumps({"segments": chunk_segments}, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        chunk_subtitle_path.write_text("", encoding="utf-8")
        chunk_raw_alignment_path.write_text("{}", encoding="utf-8")
        (chunk_dir / "asr-result.json").write_text(
            json.dumps(
                {
                    "status": "success",
                    "elapsed_ms_total": 300,
                    "phases": [],
                    "artifacts": {
                        "audio_path": str(chunk.audio_path.resolve()),
                        "transcript_path": str(chunk_transcript_path.resolve()),
                        "subtitle_path": str(chunk_subtitle_path.resolve()),
                        "raw_alignment_path": str(chunk_raw_alignment_path.resolve()),
                    },
                    "model_metadata": {"provider": "whisperx", "model_name": "large-v3"},
                    "error": None,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )


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
        assert [segment.id for segment in segments] == ["seg-000001", "seg-000002"]
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


class _RecordingProvider:
    metadata = _FakeProvider.metadata

    def __init__(self, *, mismatch_chunk_id: str | None = None):
        self.calls: list[list[str]] = []
        self.mismatch_chunk_id = mismatch_chunk_id

    def translate_segments(self, segments):
        segment_ids = [segment.id for segment in segments]
        self.calls.append(segment_ids)
        if self.mismatch_chunk_id is not None and self.mismatch_chunk_id in segment_ids:
            return []
        return [f"日语-{segment.id}" for segment in segments]


class _RecordingProofreader:
    """A deterministic constrained proofreader fake for translation-stage integration tests."""

    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on_call = fail_on_call

    def proofread_segments(self, segments):
        from app.services.proofread_deepseek import ProofreadBatchAudit, ProofreadFailure, ProofreadResult, ProofreadSegment

        corrected: list[ProofreadSegment] = []
        audits: list[ProofreadBatchAudit] = []
        for batch_index, segment in enumerate(segments):
            self.calls.append([segment.id])
            if self.fail_on_call == len(self.calls):
                raise ProofreadFailure(
                    code="proofread_invalid_response",
                    message="DeepSeek returned an invalid proofreading response.",
                )
            corrected.append(
                ProofreadSegment(
                    id=segment.id,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    text=segment.text,
                    translated_text=f"校对-{segment.translated_text}",
                )
            )
            audits.append(
                ProofreadBatchAudit(
                    batch_index=batch_index,
                    model="deepseek-test",
                    attempt_count=1,
                    elapsed_seconds=0.1,
                    changed_segment_count=1,
                    token_usage={"total_tokens": 10},
                )
            )
        return ProofreadResult(segments=corrected, batch_audits=audits)


def test_translation_requires_all_proofread_batches_before_publishing_canonical_outputs(backend_env, monkeypatch) -> None:
    # Given: three durable ASR chunks and a proofreader limited to one row per call.
    task_id = _create_task("https://www.bilibili.com/video/BV1proofread-success")
    data_dir = Path(backend_env["data_dir"])
    _prepare_chunked_asr_fixture(data_dir, task_id)
    translator = _RecordingProvider()
    proofreader = _RecordingProofreader()
    monkeypatch.setattr("app.services.translation_provider.build_translation_provider", lambda settings=None: translator)
    monkeypatch.setattr("app.services.translation_provider.build_proofreader", lambda settings: proofreader)
    monkeypatch.setenv("APP_DEEPSEEK_MAX_SEGMENTS_PER_REQUEST", "1")

    from app.db import session_scope
    from app.models import Artifact
    from app.services.translation_provider import translate_task_subtitles

    # When: translation reaches the required proofreading substep.
    with session_scope() as session:
        result = translate_task_subtitles(session, task_id)

    # Then: canonical outputs arrive only after every batch validates, with safe audit metadata.
    assert proofreader.calls == [["seg-000001"], ["seg-000002"], ["seg-000003"]]
    assert result.transcript_path.name == "subtitles.zh-ja.json"
    payload = json.loads(result.transcript_path.read_text(encoding="utf-8"))
    assert [row["translated_text"] for row in payload["segments"]] == [
        "校对-日语-seg-000001",
        "校对-日语-seg-000002",
        "校对-日语-seg-000003",
    ]
    assert (result.transcript_path.parent / "subtitles.zh-ja.preproofread.json").exists()
    audit_payload = json.loads((result.transcript_path.parent / "proofread-audit.json").read_text(encoding="utf-8"))
    assert audit_payload["batch_count"] == 3
    assert "text" not in audit_payload
    assert "translated_text" not in audit_payload
    with session_scope() as session:
        artifact_kinds = {
            artifact.kind
            for artifact in session.exec(
                select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "translation")
            ).all()
        }
    assert artifact_kinds == {
        "bilingual_preproofread_subtitle_srt",
        "bilingual_preproofread_transcript_json",
        "bilingual_proofread_audit_json",
        "bilingual_subtitle_srt",
        "bilingual_transcript_json",
    }


def test_translation_proofread_failure_never_publishes_canonical_outputs(backend_env, monkeypatch) -> None:
    # Given: a proofreader whose second batch violates the response contract.
    task_id = _create_task("https://www.bilibili.com/video/BV1proofread-failure")
    data_dir = Path(backend_env["data_dir"])
    _prepare_chunked_asr_fixture(data_dir, task_id)
    monkeypatch.setattr("app.services.translation_provider.build_translation_provider", lambda settings=None: _RecordingProvider())
    monkeypatch.setattr(
        "app.services.translation_provider.build_proofreader",
        lambda settings: _RecordingProofreader(fail_on_call=2),
    )
    monkeypatch.setenv("APP_DEEPSEEK_MAX_SEGMENTS_PER_REQUEST", "1")

    from app.db import session_scope
    from app.services.translation_provider import TranslationFailure, translate_task_subtitles

    # When / Then: a later proofread batch fails, preserving diagnostic baseline only.
    with pytest.raises(TranslationFailure) as raised:
        with session_scope() as session:
            translate_task_subtitles(session, task_id)
    assert raised.value.code == "translation_proofread_invalid_response"
    work_dir = data_dir / "tasks" / task_id / "work"
    assert (work_dir / "subtitles.zh-ja.preproofread.json").exists()
    assert not (work_dir / "subtitles.zh-ja.json").exists()
    assert not (work_dir / "subtitles.zh-ja.srt").exists()


def test_translation_final_replace_failure_removes_proofread_publication_and_marks_stage_failed(backend_env, monkeypatch) -> None:
    # Given: a final SRT replacement that fails after the final JSON replacement succeeds.
    task_id = _create_task("https://www.bilibili.com/video/BV1proofread-replace-failure")
    data_dir = Path(backend_env["data_dir"])
    _prepare_chunked_asr_fixture(data_dir, task_id)
    monkeypatch.setattr("app.services.translation_provider.build_translation_provider", lambda settings=None: _RecordingProvider())
    monkeypatch.setattr("app.services.translation_provider.build_proofreader", lambda settings: _RecordingProofreader())
    original_replace = Path.replace

    def _fail_final_srt_replace(source: Path, target: Path) -> Path:
        if target.name == "subtitles.zh-ja.srt":
            raise OSError("injected final SRT replacement failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", _fail_final_srt_replace)
    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.translation_provider import TranslationFailure, translate_task_subtitles

    # When: canonical final publication reaches its second file replacement.
    with pytest.raises(TranslationFailure) as raised:
        with session_scope() as session:
            translate_task_subtitles(session, task_id)

    # Then: no proofread publication survives, while the diagnostic baseline and failed stage state do.
    assert raised.value.code == "translation_failed"
    work_dir = data_dir / "tasks" / task_id / "work"
    assert (work_dir / "subtitles.zh-ja.preproofread.json").exists()
    assert (work_dir / "subtitles.zh-ja.preproofread.srt").exists()
    assert not (work_dir / "subtitles.zh-ja.json").exists()
    assert not (work_dir / "subtitles.zh-ja.srt").exists()
    assert not (work_dir / "proofread-audit.json").exists()
    with session_scope() as session:
        artifact_kinds = {
            artifact.kind
            for artifact in session.exec(
                select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "translation")
            ).all()
        }
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "translation")
        ).one()
        stage_status = stage.status
        stage_summary = stage.summary
    assert artifact_kinds == {"bilingual_preproofread_subtitle_srt", "bilingual_preproofread_transcript_json"}
    assert stage_status == "failed"
    assert stage_summary == "translation_failed"


def test_translation_final_metadata_failure_removes_final_files_and_artifacts_but_keeps_preproofread(
    backend_env, monkeypatch
) -> None:
    # Given: a completed proofread whose second canonical artifact metadata write fails.
    task_id = _create_task("https://www.bilibili.com/video/BV1proofread-persist-failure")
    data_dir = Path(backend_env["data_dir"])
    _prepare_chunked_asr_fixture(data_dir, task_id)
    monkeypatch.setattr("app.services.translation_provider.build_translation_provider", lambda settings=None: _RecordingProvider())
    monkeypatch.setattr("app.services.translation_provider.build_proofreader", lambda settings: _RecordingProofreader())
    from app.services import translation_provider

    persist_calls = 0
    original_persist = translation_provider.persist_artifact_metadata

    def _persist_until_second_final_then_fail(*args, **kwargs):
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 4:
            raise OSError("injected canonical artifact persistence failure")
        return original_persist(*args, **kwargs)

    monkeypatch.setattr(translation_provider, "persist_artifact_metadata", _persist_until_second_final_then_fail)

    from app.db import session_scope
    from app.models import Artifact, TaskStage
    from app.services.translation_provider import TranslationFailure, translate_task_subtitles

    # When: the final publication reaches a partial database persistence failure.
    with pytest.raises(TranslationFailure) as raised:
        with session_scope() as session:
            translate_task_subtitles(session, task_id)

    # Then: only the diagnostic baseline remains, and the stage has a durable failure state.
    assert raised.value.code == "translation_failed"
    work_dir = data_dir / "tasks" / task_id / "work"
    assert (work_dir / "subtitles.zh-ja.preproofread.json").exists()
    assert (work_dir / "subtitles.zh-ja.preproofread.srt").exists()
    assert not (work_dir / "subtitles.zh-ja.json").exists()
    assert not (work_dir / "subtitles.zh-ja.srt").exists()
    assert not (work_dir / "proofread-audit.json").exists()
    with session_scope() as session:
        artifact_kinds = {
            artifact.kind
            for artifact in session.exec(
                select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "translation")
            ).all()
        }
        stage = session.exec(
            select(TaskStage).where(TaskStage.task_id == task_id).where(TaskStage.name == "translation")
        ).one()
        stage_status = stage.status
        stage_summary = stage.summary
    assert artifact_kinds == {"bilingual_preproofread_subtitle_srt", "bilingual_preproofread_transcript_json"}
    assert stage_status == "failed"
    assert stage_summary == "translation_failed"


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


class _ModernFakeTokenizer(_FakeTokenizer):
    def __init__(self):
        super().__init__()
        del self.lang_code_to_id

    def convert_tokens_to_ids(self, token: str) -> int:
        assert token == "jpn_Jpan"
        return 7


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


def test_translate_chunks_in_order_reuses_valid_cache_and_publishes_preproofread_outputs(backend_env, monkeypatch) -> None:
    # Given: source-global rows and three durable five-minute media chunks.
    task_id = _create_task("https://www.bilibili.com/video/BV1chunktranslation001")
    data_dir = Path(backend_env["data_dir"])
    _prepare_chunked_asr_fixture(data_dir, task_id)
    provider = _RecordingProvider()
    monkeypatch.setattr("app.services.translation_provider.build_translation_provider", lambda settings=None: provider)
    perf_values = iter([10.0, 12.25, 15.0, 16.0, 20.0, 22.0])
    monkeypatch.setattr("app.services.translation_provider.time.perf_counter", lambda: next(perf_values))

    from app.db import session_scope
    from app.models import Artifact, TaskExecutionProgress
    from app.services.translation_provider import translate_task_subtitles

    # When: translation runs once, then a single cached chunk is removed and retried.
    with session_scope() as session:
        first_result = translate_task_subtitles(session, task_id)
    (data_dir / "tasks" / task_id / "work" / "translation-chunks" / "chunk-0001.json").unlink()
    with session_scope() as session:
        second_result = translate_task_subtitles(session, task_id)
    provider.metadata = {**provider.metadata, "model_name": "replacement-model"}
    with session_scope() as session:
        translate_task_subtitles(session, task_id)

    # Then: each source chunk is translated independently and retry only invokes the missing one.
    assert provider.calls == [
        ["seg-000001"],
        ["seg-000002"],
        ["seg-000003"],
        ["seg-000002"],
        ["seg-000001"],
        ["seg-000002"],
        ["seg-000003"],
    ]
    assert first_result.transcript_path.name == "subtitles.zh-ja.json"
    assert second_result.subtitle_path.name == "subtitles.zh-ja.srt"
    transcript_payload = json.loads(second_result.transcript_path.read_text(encoding="utf-8"))
    assert [segment["id"] for segment in transcript_payload["segments"]] == [
        "seg-000001",
        "seg-000002",
        "seg-000003",
    ]
    assert [segment["start_seconds"] for segment in transcript_payload["segments"]] == [0.0, 300.0, 600.0]
    assert transcript_payload["segments"][1]["words"][0]["start_seconds"] == 300.0
    assert (second_result.transcript_path.parent / "subtitles.zh-ja.preproofread.json").exists()
    assert (second_result.transcript_path.parent / "subtitles.zh-ja.preproofread.srt").exists()

    with session_scope() as session:
        artifacts = session.exec(
            select(Artifact).where(Artifact.task_id == task_id).where(Artifact.stage_name == "translation")
        ).all()
        progress = session.get(TaskExecutionProgress, task_id)
        artifact_kinds = {artifact.kind for artifact in artifacts}
        progress_details = (
            (progress.stage_name, progress.current_phase, progress.latest_message) if progress is not None else None
        )
    assert artifact_kinds == {
        "bilingual_proofread_audit_json",
        "bilingual_preproofread_subtitle_srt",
        "bilingual_preproofread_transcript_json",
        "bilingual_subtitle_srt",
        "bilingual_transcript_json",
    }
    assert progress_details == (
        "translation",
        "proofread",
        "Translation proofread",
    )


def test_translate_chunk_fails_when_provider_returns_mismatched_output(backend_env, monkeypatch) -> None:
    # Given: a three-chunk ASR transcript and a provider with an invalid middle response.
    task_id = _create_task("https://www.bilibili.com/video/BV1chunktranslation002")
    data_dir = Path(backend_env["data_dir"])
    _prepare_chunked_asr_fixture(data_dir, task_id)
    provider = _RecordingProvider(mismatch_chunk_id="seg-000002")
    monkeypatch.setattr("app.services.translation_provider.build_translation_provider", lambda settings=None: provider)

    from app.db import session_scope
    from app.services.translation_provider import TranslationFailure, translate_task_subtitles

    # When / Then: an invalid chunk result fails and never publishes a merged diagnostic output.
    with pytest.raises(TranslationFailure, match="returned 0 segments"):
        with session_scope() as session:
            translate_task_subtitles(session, task_id)
    work_dir = data_dir / "tasks" / task_id / "work"
    assert not (work_dir / "subtitles.zh-ja.preproofread.json").exists()
    assert not (work_dir / "subtitles.zh-ja.preproofread.srt").exists()


def test_translate_rejects_aggregate_transcript_that_differs_from_verified_asr_chunks(backend_env, monkeypatch) -> None:
    # Given: durable chunk manifests and an aggregate transcript whose middle row was altered afterwards.
    task_id = _create_task("https://www.bilibili.com/video/BV1chunktranslation-integrity")
    data_dir = Path(backend_env["data_dir"])
    transcript_path = _prepare_chunked_asr_fixture(data_dir, task_id)
    aggregate = json.loads(transcript_path.read_text(encoding="utf-8"))
    aggregate["segments"][1]["text"] = "被篡改的字幕"
    transcript_path.write_text(json.dumps(aggregate, ensure_ascii=False), encoding="utf-8")
    provider = _RecordingProvider()
    monkeypatch.setattr("app.services.translation_provider.build_translation_provider", lambda settings=None: provider)

    from app.db import session_scope
    from app.services.translation_provider import TranslationFailure, translate_task_subtitles

    # When / Then: translation refuses the unbound aggregate and never invokes the provider.
    with pytest.raises(TranslationFailure, match="does not match validated per-chunk ASR output") as exc_info:
        with session_scope() as session:
            translate_task_subtitles(session, task_id)
    assert exc_info.value.code == "invalid_chunk_output"
    assert provider.calls == []


@pytest.mark.parametrize(
    ("artifact_name", "field_name", "tampered_value"),
    [
        ("asr-aggregate-manifest.json", "elapsed_seconds", 42.0),
        ("asr-segments.json", "elapsed_seconds", 42.0),
        ("asr-segments.json", "model_metadata", {"provider": "tampered"}),
        ("asr-segments.json", "segment_count", 42),
    ],
)
def test_translate_rejects_aggregate_asr_metadata_that_does_not_bind_chunks(
    backend_env,
    monkeypatch,
    artifact_name: str,
    field_name: str,
    tampered_value: float | int | dict[str, str],
) -> None:
    # Given: otherwise valid per-chunk ASR manifests and a tampered aggregate-only metadata field.
    task_id = _create_task("https://www.bilibili.com/video/BV1chunktranslation-aggregate-metadata")
    data_dir = Path(backend_env["data_dir"])
    transcript_path = _prepare_chunked_asr_fixture(data_dir, task_id)
    artifact_path = transcript_path.parent / artifact_name
    aggregate_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    aggregate_payload[field_name] = tampered_value
    artifact_path.write_text(json.dumps(aggregate_payload, ensure_ascii=False), encoding="utf-8")
    provider = _RecordingProvider()
    monkeypatch.setattr("app.services.translation_provider.build_translation_provider", lambda settings=None: provider)

    from app.db import session_scope
    from app.services.translation_provider import TranslationFailure, translate_task_subtitles

    # When / Then: no aggregate field may reach the translator without binding to valid chunk output.
    with pytest.raises(TranslationFailure) as exc_info:
        with session_scope() as session:
            translate_task_subtitles(session, task_id)
    assert exc_info.value.code == "invalid_chunk_output"
    assert provider.calls == []


def test_translate_segments_preserves_ids_timestamps_and_writes_preproofread_bilingual_outputs(backend_env, monkeypatch) -> None:
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
    assert result.transcript_path.name == "subtitles.zh-ja.json"
    assert result.subtitle_path.name == "subtitles.zh-ja.srt"
    assert result.elapsed_seconds == 2.25
    assert transcript_payload["segments"][0]["id"] == "seg-000001"
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
    assert stage_summary == "Generated proofread bilingual Chinese/Japanese subtitles"
    assert artifact_kinds == {
        "bilingual_preproofread_subtitle_srt",
        "bilingual_preproofread_transcript_json",
        "bilingual_proofread_audit_json",
        "bilingual_subtitle_srt",
        "bilingual_transcript_json",
    }


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


def test_hf_provider_supports_modern_nllb_tokenizer_without_lang_code_to_id(monkeypatch) -> None:
    monkeypatch.setattr("app.services.translation_hf._load_torch_module", lambda: _FakeTorchModule())

    from app.services.subtitles import SubtitleSegment
    from app.services.translation_hf import HuggingFaceTranslationProvider

    tokenizer = _ModernFakeTokenizer()
    model = _FakeModel()
    provider = HuggingFaceTranslationProvider(
        model_name="facebook/nllb-200-distilled-600M",
        device="cpu",
        source_language_code="zho_Hans",
        target_language_code="jpn_Jpan",
    )
    provider._tokenizer = tokenizer
    provider._model = model

    translated_texts = provider.translate_segments(
        [SubtitleSegment(id="seg-0001", start_seconds=0.0, end_seconds=1.0, text="你好", words=None)]
    )

    assert translated_texts == ["こんにちは"]
    assert model.generate_calls[0]["forced_bos_token_id"] == 7


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
