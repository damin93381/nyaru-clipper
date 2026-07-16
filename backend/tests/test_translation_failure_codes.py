from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "expected_code",
    [
        "translation_proofread_missing_api_key",
        "translation_proofread_auth_failed",
        "translation_proofread_billing_failed",
        "translation_proofread_rate_limit",
        "translation_proofread_timeout",
        "translation_proofread_invalid_response",
    ],
)
def test_translation_proofread_failures_have_stable_stage_failure_codes(expected_code: str) -> None:
    # Given: a safe translation-layer proofread failure.
    from app.services.translation_provider import TranslationFailure
    from app.services.failure_codes import failure_code_from_exception

    # When: the pipeline records it at the canonical translation stage boundary.
    actual_code = failure_code_from_exception(
        "translation",
        TranslationFailure(code=expected_code, message="safe operator guidance"),
    )

    # Then: the browser-facing failure code remains specific and deterministic.
    assert actual_code == expected_code
