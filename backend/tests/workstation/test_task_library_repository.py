from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlmodel import Session, select


def _reset_runtime_state() -> None:
    from app.db import reset_db_runtime

    reset_db_runtime()


@pytest.fixture()
def session(tmp_path, monkeypatch) -> Session:
    # Given: an isolated, migrated workstation database.
    database_path = tmp_path / "task-state.sqlite3"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{database_path}")
    _reset_runtime_state()

    from app.db import get_engine, init_db

    init_db()
    with Session(get_engine()) as database_session:
        yield database_session


def _seed_library(session: Session) -> None:
    from app.models import MediaSource, Task, TaskTag, TaskTagLink

    base_time = datetime(2026, 7, 12, tzinfo=timezone.utc)
    session.add_all([TaskTag(name="summer"), TaskTag(name="music")])
    for index in range(1_025):
        status = ("pending", "running", "success", "failed", "cancelled")[index % 5]
        title = f"夏日 task {index:04d}" if status in {"running", "failed"} else f"Winter task {index:04d}"
        task_id = f"task-{index:04d}"
        task = Task(
            id=task_id,
            source_url=f"file:///fixtures/{task_id}.mp4",
            normalized_source_url=f"file:///fixtures/{task_id}.mp4",
            status=status,
            title=title,
            archived_at=base_time if index % 97 == 0 else None,
            storage_bytes=index,
            created_at=base_time + timedelta(minutes=index),
            updated_at=base_time + timedelta(minutes=index // 2),
        )
        session.add(task)
        session.add(
            MediaSource(
                task_id=task_id,
                kind="bilibili" if index % 2 == 0 else "local",
                locator=task.source_url,
                display_name=f"Source {index:04d}",
            )
        )
        if index % 10 == 0:
            session.add(TaskTagLink(task_id=task_id, tag_name="summer"))
        if index % 15 == 0:
            session.add(TaskTagLink(task_id=task_id, tag_name="music"))
    session.commit()


def test_list_workstation_tasks_filters_pages_and_clamps_results(session: Session) -> None:
    # Given: more than one page of mixed workstation tasks.
    _seed_library(session)
    from app.api.schemas.workstation import TaskListQuery
    from app.repositories.workstation import list_workstation_tasks

    # When: a filtered page is requested.
    page = list_workstation_tasks(
        session,
        TaskListQuery(query="夏日", statuses=["running", "failed"], page=2, page_size=50),
    )

    # Then: filtering happens before the bounded server-side page is returned.
    assert page.page == 2
    assert page.page_size == 50
    assert page.total >= len(page.items)
    assert all("夏日" in item.title for item in page.items)
    assert all(item.status in {"running", "failed"} for item in page.items)
    assert len(page.items) <= 50

    # When: a client requests a page larger than the public maximum.
    clamped_page = list_workstation_tasks(session, TaskListQuery(page=1, page_size=500))

    # Then: the repository clamps it before issuing the SQL page query.
    assert clamped_page.page_size == 100
    assert len(clamped_page.items) == 100


def test_list_workstation_tasks_uses_stable_order_tags_and_archive_default(session: Session) -> None:
    # Given: tasks with tied timestamps, tags, and one archived match.
    _seed_library(session)
    from app.api.schemas.workstation import TaskListQuery
    from app.models import Task
    from app.repositories.workstation import list_workstation_tasks

    tied_time = datetime(2026, 8, 1, tzinfo=timezone.utc)
    for task_id in ("task-0010", "task-0020"):
        task = session.get(Task, task_id)
        assert task is not None
        task.updated_at = tied_time
    archived = session.get(Task, "task-0000")
    assert archived is not None
    archived.title = "夏日 archived"
    session.commit()

    # When: matching tasks are listed by tag without including archives.
    page = list_workstation_tasks(session, TaskListQuery(tag="summer", page=1, page_size=100))

    # Then: archive exclusion and deterministic updated_at/id ordering are preserved.
    assert "task-0000" not in {item.task_id for item in page.items}
    assert {"task-0010", "task-0020"}.issubset({item.task_id for item in page.items})
    tied_ids = [item.task_id for item in page.items if item.task_id in {"task-0010", "task-0020"}]
    assert tied_ids == ["task-0020", "task-0010"]
    assert all("summer" in item.tags for item in page.items)


def test_list_workstation_tasks_escapes_like_wildcards_without_fts(session: Session, monkeypatch) -> None:
    # Given: a literal title that contains SQL LIKE wildcard characters.
    from app.api.schemas.workstation import TaskListQuery
    from app.models import MediaSource, Task
    import app.repositories.workstation as workstation_repository

    session.add_all(
        [
            Task(
                id="task-literal",
                source_url="file:///fixtures/literal.mp4",
                normalized_source_url="file:///fixtures/literal.mp4",
                title="100%_complete",
            ),
            Task(
                id="task-near-match",
                source_url="file:///fixtures/near.mp4",
                normalized_source_url="file:///fixtures/near.mp4",
                title="100AAcomplete",
            ),
        ]
    )
    session.add_all(
        [
            MediaSource(task_id="task-literal", kind="local", locator="file:///fixtures/literal.mp4"),
            MediaSource(task_id="task-near-match", kind="local", locator="file:///fixtures/near.mp4"),
        ]
    )
    session.commit()
    monkeypatch.setattr(workstation_repository, "_sqlite_fts_available", lambda _: False)

    # When: the fallback search receives the wildcard-containing literal.
    page = workstation_repository.list_workstation_tasks(session, TaskListQuery(query="100%_complete"))

    # Then: it matches only the literal title rather than treating % and _ as wildcards.
    assert [item.task_id for item in page.items] == ["task-literal"]


def test_get_task_library_summary_counts_bucketed_tasks_and_storage(session: Session) -> None:
    # Given: a library with each status bucket and archived tasks.
    _seed_library(session)
    from app.models import Task
    from app.repositories.workstation import get_task_library_summary

    tasks = session.exec(select(Task)).all()
    expected = {
        "active": sum(task.status == "running" and task.archived_at is None for task in tasks),
        "queued": sum(task.status == "pending" and task.archived_at is None for task in tasks),
        "review_required": sum(task.status == "success" and task.archived_at is None for task in tasks),
        "failed": sum(task.status == "failed" and task.archived_at is None for task in tasks),
        "archived": sum(task.archived_at is not None for task in tasks),
        "storage_bytes": sum(task.storage_bytes for task in tasks),
    }

    # When: the library summary is requested.
    summary = get_task_library_summary(session)

    # Then: each dashboard bucket is counted in SQL with total storage retained.
    assert summary.model_dump() == expected


def test_get_workstation_task_overview_projects_unstarted_legacy_stages(session: Session) -> None:
    # Given: a pending task that predates PipelineRun creation.
    from app.models import CANONICAL_STAGES, MediaSource, Task, TaskStage
    from app.repositories.workstation import get_workstation_task_overview

    task_id = "task-pending"
    session.add(
        Task(
            id=task_id,
            source_url="file:///fixtures/pending.mp4",
            normalized_source_url="file:///fixtures/pending.mp4",
            status="pending",
            title="Pending source",
        )
    )
    session.add(MediaSource(task_id=task_id, kind="local", locator="file:///fixtures/pending.mp4"))
    session.add_all([TaskStage(task_id=task_id, name=name, status="pending") for name in CANONICAL_STAGES])
    session.commit()

    # When: the workstation overview is requested.
    overview = get_workstation_task_overview(session, task_id)

    # Then: it exposes all seven planned legacy stages without inventing a run ID.
    assert overview is not None
    assert overview.pipeline_run_id is None
    assert [stage.name for stage in overview.stages] == CANONICAL_STAGES
    assert all(stage.planned for stage in overview.stages)


def test_get_workstation_task_overview_redacts_nested_absolute_paths_from_artifact_metadata(
    session: Session,
) -> None:
    # Given: artifact metadata with sensitive POSIX and Windows host paths.
    from app.models import Artifact, MediaSource, Task
    from app.repositories.workstation import get_workstation_task_overview

    task_id = "task-artifact-metadata"
    raw_paths = {
        "source_audio_path": "/mnt/recordings/raw/audio.wav",
        "source_transcript_path": "C:\\Users\\operator\\transcript.json",
        "source_video_path": "/var/lib/nyaru/source.mp4",
        "output_file_path": "D:\\exports\\clip.mp4",
    }
    metadata = {
        **raw_paths,
        "nested": {"outputs": [raw_paths["source_audio_path"], {"path": raw_paths["output_file_path"]}]},
        "relative_path": "exports/clip.mp4",
    }
    session.add(
        Task(
            id=task_id,
            source_url="file:///fixtures/metadata.mp4",
            normalized_source_url="file:///fixtures/metadata.mp4",
            title="Metadata fixture",
        )
    )
    session.add(MediaSource(task_id=task_id, kind="local", locator="file:///fixtures/metadata.mp4"))
    session.add(
        Artifact(
            task_id=task_id,
            stage_name="asr",
            kind="transcript_json",
            path="/var/lib/nyaru/tasks/task-artifact-metadata/work/transcript.json",
            metadata_json=json.dumps(metadata),
        )
    )
    session.commit()

    # When: the v2 overview serializes its artifact metadata.
    overview = get_workstation_task_overview(session, task_id)

    # Then: metadata is recursively redacted while the content URL remains public API identity.
    assert overview is not None
    public_artifact = overview.artifacts[0]
    public_metadata = json.loads(public_artifact.metadata_json)
    assert public_artifact.path.endswith("/content/transcript.json")
    assert public_metadata["source_audio_path"] == "[path]"
    assert public_metadata["source_transcript_path"] == "[path]"
    assert public_metadata["source_video_path"] == "[path]"
    assert public_metadata["output_file_path"] == "[path]"
    assert public_metadata["nested"]["outputs"] == ["[path]", {"path": "[path]"}]
    assert public_metadata["relative_path"] == "exports/clip.mp4"
    serialized_overview = overview.model_dump_json()
    assert all(raw_path not in serialized_overview for raw_path in raw_paths.values())


def test_recovery_actions_are_discriminated_and_reject_unknown_identifiers(session: Session) -> None:
    # Given: an ASR missing-model failure, which provides both known recovery actions.
    from app.api.schemas.workstation import (
        DownloadAsrModelRecoveryAction,
        RecoveryAction,
        RetryStageRecoveryAction,
    )
    from app.models import MediaSource, Task, TaskStage
    from app.repositories.workstation import get_workstation_task_overview

    task_id = "task-recovery-actions"
    session.add(
        Task(
            id=task_id,
            source_url="file:///fixtures/recovery.mp4",
            normalized_source_url="file:///fixtures/recovery.mp4",
            status="failed",
            title="Recovery fixture",
        )
    )
    session.add(MediaSource(task_id=task_id, kind="local", locator="file:///fixtures/recovery.mp4"))
    session.add(TaskStage(task_id=task_id, name="asr", status="failed", failure_code="asr_missing_model"))
    session.commit()

    # When: the v2 overview serializes backend-authored recovery actions.
    overview = get_workstation_task_overview(session, task_id)

    # Then: the variants retain their exact payload contracts and unknown IDs are rejected.
    assert overview is not None
    download_action, retry_action = overview.recovery_actions
    assert isinstance(download_action, DownloadAsrModelRecoveryAction)
    assert download_action.payload.model_keys == ["whisperx", "alignment"]
    assert isinstance(retry_action, RetryStageRecoveryAction)
    assert retry_action.payload.stage_name == "asr"
    with pytest.raises(ValidationError):
        TypeAdapter(RecoveryAction).validate_python(
            {
                "id": "unknown_action",
                "label_key": "unknown_action",
                "description_key": "unknown_action",
                "enabled": True,
                "disabled_reason": None,
                "method": "POST",
                "endpoint": "/api/tasks/task-recovery-actions/unknown",
                "payload": {},
                "confirmation_required": False,
                "success_behavior": "poll_task",
            }
        )
    with pytest.raises(ValidationError):
        TypeAdapter(RecoveryAction).validate_python(
            {
                "id": "retry_stage",
                "label_key": "retry_stage",
                "description_key": "retry_stage",
                "enabled": True,
                "disabled_reason": None,
                "method": "POST",
                "endpoint": "/api/tasks/task-recovery-actions/retry",
                "payload": {"stage_name": "asr", "unexpected": "value"},
                "confirmation_required": False,
                "success_behavior": "poll_task",
            }
        )


def test_get_workstation_task_overview_redacts_host_paths_from_all_user_visible_text(
    session: Session,
) -> None:
    # Given: host paths in every v2 overview text surface.
    from app.models import Artifact, MediaSource, Task, TaskExecutionProgress, TaskStage
    from app.repositories.workstation import get_workstation_task_overview
    from app.services.storage import log_file_for_stage

    task_id = "task-visible-paths"
    raw_paths = [
        "/home/operator/models/whisper.bin",
        "/mnt/recordings/source.wav",
        "/var/lib/nyaru/transcript.json",
        "C:\\Users\\operator\\cache",
        "D:\\exports\\clip.mp4",
        "\\\\server\\share\\source.mp4",
    ]
    session.add(
        Task(
            id=task_id,
            source_url="file:///fixtures/visible-paths.mp4",
            normalized_source_url="file:///fixtures/visible-paths.mp4",
            status="running",
            title="Visible-path fixture",
        )
    )
    session.add(MediaSource(task_id=task_id, kind="local", locator="file:///fixtures/visible-paths.mp4"))
    session.add(
        TaskStage(
            task_id=task_id,
            name="asr",
            status="running",
            summary=f"ASR loaded {raw_paths[0]} and {raw_paths[3]}; retryable diagnostic.",
        )
    )
    session.add(
        TaskExecutionProgress(
            task_id=task_id,
            stage_name="asr",
            current_phase="transcribe",
            phase_index=2,
            phase_count=5,
            latest_message=f"Reading {raw_paths[1]}; model remains available.",
            phase_timings_json=json.dumps(
                [
                    {
                        "message": f"Wrote {raw_paths[4]}",
                        "nested": {"source": raw_paths[2], "share": raw_paths[5]},
                        "diagnostic": "phase completed",
                    }
                ]
            ),
        )
    )
    session.add(
        Artifact(
            task_id=task_id,
            stage_name="asr",
            kind="transcript_json",
            path="/var/lib/nyaru/tasks/task-visible-paths/work/transcript.json",
            metadata_json=json.dumps({"paths": raw_paths}),
        )
    )
    session.commit()
    log_file_for_stage(task_id, "asr").write_text(
        f"worker inspected {raw_paths[5]}; retryable diagnostic.\n",
        encoding="utf-8",
    )

    # When: the v2 overview is serialized.
    overview = get_workstation_task_overview(session, task_id)

    # Then: all host paths are removed while useful non-path diagnostics remain.
    assert overview is not None
    assert overview.stages[0].summary == "ASR loaded [path] and [path]; retryable diagnostic."
    assert overview.safe_logs[0].summary == "worker inspected [path]; retryable diagnostic."
    assert overview.execution_progress is not None
    assert overview.execution_progress.latest_message == "Reading [path]; model remains available."
    assert overview.execution_progress.phases == [
        {
            "message": "Wrote [path]",
            "nested": {"source": "[path]", "share": "[path]"},
            "diagnostic": "phase completed",
        }
    ]
    assert json.loads(overview.artifacts[0].metadata_json)["paths"] == ["[path]"] * len(raw_paths)
    serialized_overview = overview.model_dump_json()
    assert all(raw_path not in serialized_overview for raw_path in raw_paths)


def test_workstation_task_source_labels_do_not_expose_local_host_paths(session: Session) -> None:
    # Given: local/file sources with POSIX, Windows-drive, UNC, display-name, and empty locators.
    from app.api.schemas.workstation import TaskListQuery
    from app.models import MediaSource, Task
    from app.repositories.workstation import get_workstation_task_overview, list_workstation_tasks

    source_fixtures = [
        ("task-file", "file:///home/operator/capture.mp4", None, "capture.mp4"),
        ("task-windows", "C:\\Users\\operator\\Videos\\winter.mkv", None, "winter.mkv"),
        ("task-unc", "\\\\server\\share\\source.mp4", None, "source.mp4"),
        ("task-display", "file:///mnt/private/source.mp4", "Imported /home/operator/source.mp4", "Imported [path]"),
        ("task-empty", "", None, "Local source"),
    ]
    raw_locators = [fixture[1] for fixture in source_fixtures[:-1]]
    for task_id, locator, display_name, _ in source_fixtures:
        session.add(
            Task(
                id=task_id,
                source_url=locator or "file:///var/lib/nyaru/unknown.mp4",
                normalized_source_url=locator or f"file:///var/lib/nyaru/{task_id}.mp4",
                title=task_id,
            )
        )
        session.add(
            MediaSource(
                task_id=task_id,
                kind="local",
                locator=locator,
                display_name=display_name,
            )
        )
    session.commit()

    # When: the same local sources are projected in the list and an overview.
    page = list_workstation_tasks(session, TaskListQuery(page_size=50))
    overview = get_workstation_task_overview(session, "task-file")

    # Then: labels retain useful filenames or a generic label without raw host paths.
    labels = {item.task_id: item.source_label for item in page.items}
    assert labels == {task_id: expected_label for task_id, _, _, expected_label in source_fixtures}
    assert overview is not None
    assert overview.source_label == "capture.mp4"
    assert all(locator not in page.model_dump_json() for locator in raw_locators)
    assert all(locator not in overview.model_dump_json() for locator in raw_locators)


def test_workstation_source_labels_normalize_file_uri_display_names(session: Session) -> None:
    # Given: display names that themselves contain plain and encoded local file URIs.
    from app.api.schemas.workstation import TaskListQuery
    from app.models import MediaSource, Task
    from app.repositories.workstation import get_workstation_task_overview, list_workstation_tasks

    display_names = {
        "task-display-uri": ("file:///home/operator/capture.mp4", "capture.mp4"),
        "task-display-encoded-uri": ("file:///home/operator/capture%20copy.mp4", "capture copy.mp4"),
        "task-display-embedded-uri": ("Imported file:///home/operator/capture.mp4", "Imported capture.mp4"),
        "task-display-embedded-encoded-uri": (
            "Imported file:///home/operator/capture%20copy.mp4",
            "Imported capture copy.mp4",
        ),
    }
    for task_id, (display_name, _) in display_names.items():
        session.add(
            Task(
                id=task_id,
                source_url="file:///mnt/private/original.mp4",
                normalized_source_url=f"file:///mnt/private/{task_id}.mp4",
                title=task_id,
            )
        )
        session.add(
            MediaSource(
                task_id=task_id,
                kind="local",
                locator="file:///mnt/private/original.mp4",
                display_name=display_name,
            )
        )
    session.commit()

    # When: file-URI display names are projected through the v2 list and overview.
    page = list_workstation_tasks(session, TaskListQuery(page_size=50))
    overview = get_workstation_task_overview(session, "task-display-embedded-uri")

    # Then: filenames remain useful without exposing either URI or its host path.
    labels = {item.task_id: item.source_label for item in page.items}
    assert labels == {task_id: expected_label for task_id, (_, expected_label) in display_names.items()}
    assert overview is not None
    assert overview.source_label == "Imported capture.mp4"
    serialized = f"{page.model_dump_json()}\n{overview.model_dump_json()}"
    assert all(display_name not in serialized for display_name, _ in display_names.values())
    assert "/home/operator" not in serialized
