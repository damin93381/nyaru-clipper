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
TRANSLATION_PROOFREAD_MISSING_API_KEY = "translation_proofread_missing_api_key"
TRANSLATION_PROOFREAD_AUTH_FAILED = "translation_proofread_auth_failed"
TRANSLATION_PROOFREAD_BILLING_FAILED = "translation_proofread_billing_failed"
TRANSLATION_PROOFREAD_RATE_LIMIT = "translation_proofread_rate_limit"
TRANSLATION_PROOFREAD_TIMEOUT = "translation_proofread_timeout"
TRANSLATION_PROOFREAD_TRANSIENT_EXHAUSTED = "translation_proofread_transient_exhausted"
TRANSLATION_PROOFREAD_INVALID_RESPONSE = "translation_proofread_invalid_response"
TRANSLATION_PROOFREAD_HTTP_ERROR = "translation_proofread_http_error"
TRANSLATION_PROOFREAD_FAILED = "translation_proofread_failed"

KNOWN_FAILURE_CODES = {
    UNKNOWN_FAILURE,
    ASR_MISSING_MODEL,
    ASR_OOM,
    ASR_ALIGNMENT_FAILED,
    ASR_CHILD_FAILED,
    MALFORMED_PROGRESS_EVENT,
    STALE_JOB_RECOVERED,
    CANCELLED,
    TRANSLATION_PROOFREAD_MISSING_API_KEY,
    TRANSLATION_PROOFREAD_AUTH_FAILED,
    TRANSLATION_PROOFREAD_BILLING_FAILED,
    TRANSLATION_PROOFREAD_RATE_LIMIT,
    TRANSLATION_PROOFREAD_TIMEOUT,
    TRANSLATION_PROOFREAD_TRANSIENT_EXHAUSTED,
    TRANSLATION_PROOFREAD_INVALID_RESPONSE,
    TRANSLATION_PROOFREAD_HTTP_ERROR,
    TRANSLATION_PROOFREAD_FAILED,
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
