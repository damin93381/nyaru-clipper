from __future__ import annotations

from typing import Any

UNKNOWN_FAILURE = "unknown_failure"
ASR_MISSING_MODEL = "asr_missing_model"
ASR_OOM = "asr_oom"
ASR_ALIGNMENT_FAILED = "asr_alignment_failed"
ASR_CHILD_FAILED = "asr_child_failed"
MALFORMED_PROGRESS_EVENT = "malformed_progress_event"
STALE_JOB_RECOVERED = "stale_job_recovered"
CANCELLED = "cancelled"

KNOWN_FAILURE_CODES = {
    UNKNOWN_FAILURE,
    ASR_MISSING_MODEL,
    ASR_OOM,
    ASR_ALIGNMENT_FAILED,
    ASR_CHILD_FAILED,
    MALFORMED_PROGRESS_EVENT,
    STALE_JOB_RECOVERED,
    CANCELLED,
}

_ASR_CODE_MAP = {
    "missing_model": ASR_MISSING_MODEL,
    "asr_missing_model": ASR_MISSING_MODEL,
    "oom": ASR_OOM,
    "asr_oom": ASR_OOM,
    "alignment_failed": ASR_ALIGNMENT_FAILED,
    "asr_alignment_failed": ASR_ALIGNMENT_FAILED,
    "asr_child_failed": ASR_CHILD_FAILED,
    "invalid_result_manifest": ASR_CHILD_FAILED,
    "malformed_progress_event": MALFORMED_PROGRESS_EVENT,
}


def normalize_failure_code(stage_name: str | None, code: str | None) -> str | None:
    if code is None:
        return None
    normalized = code.strip()
    if not normalized:
        return None
    if normalized in KNOWN_FAILURE_CODES:
        return normalized
    if stage_name == "asr":
        return _ASR_CODE_MAP.get(normalized, ASR_CHILD_FAILED)
    if normalized == "cancelled":
        return CANCELLED
    return UNKNOWN_FAILURE


def failure_code_from_exception(stage_name: str | None, exc: Exception) -> str:
    raw_code = getattr(exc, "code", None)
    code = raw_code if isinstance(raw_code, str) else None
    return normalize_failure_code(stage_name, code) or UNKNOWN_FAILURE


def failure_code_from_stage(stage: Any) -> str | None:
    if getattr(stage, "status", None) != "failed":
        return None
    persisted = getattr(stage, "failure_code", None)
    if isinstance(persisted, str) and persisted.strip():
        return normalize_failure_code(getattr(stage, "name", None), persisted)
    summary = getattr(stage, "summary", None)
    if isinstance(summary, str) and summary.strip():
        return normalize_failure_code(getattr(stage, "name", None), summary)
    return UNKNOWN_FAILURE
