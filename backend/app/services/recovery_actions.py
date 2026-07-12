from __future__ import annotations

from typing import Any

from app.models import TaskStage
from app.services.failure_codes import ASR_MISSING_MODEL, failure_code_from_stage

_STAGE_LABELS = {
    "ingest": "Ingest",
    "media_prep": "Media preparation",
    "asr": "ASR",
    "translation": "Translation",
    "highlight": "Highlight",
    "export": "Export",
    "report": "Report",
}


def stage_display_label(stage_name: str) -> str:
    return _STAGE_LABELS.get(stage_name, stage_name.replace("_", " ").title())


def serialize_recovery_actions(*, task_id: str, task_status: str, stages: list[TaskStage]) -> list[dict[str, Any]]:
    failed_stage = next((stage for stage in stages if stage.status == "failed"), None)
    if task_status != "failed" or failed_stage is None:
        return []

    actions: list[dict[str, Any]] = []
    failure_code = failure_code_from_stage(failed_stage)
    if failed_stage.name == "asr" and failure_code == ASR_MISSING_MODEL:
        actions.append(
            {
                "id": "download_asr_model",
                "label_key": "download_asr_model",
                "description_key": "download_asr_model",
                "enabled": True,
                "disabled_reason": None,
                "method": "POST",
                "endpoint": f"/api/tasks/{task_id}/asr/models/download",
                "payload": {"model_keys": ["whisperx", "alignment"]},
                "confirmation_required": False,
                "success_behavior": "retry_stage_after_success",
            }
        )

    actions.append(
        {
            "id": "retry_stage",
            "label_key": "retry_stage",
            "description_key": "retry_stage",
            "enabled": True,
            "disabled_reason": None,
            "method": "POST",
            "endpoint": f"/api/tasks/{task_id}/retry",
            "payload": {"stage_name": failed_stage.name},
            "confirmation_required": False,
            "success_behavior": "poll_task",
        }
    )
    return actions
