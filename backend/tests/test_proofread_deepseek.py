from __future__ import annotations

import json

import httpx
import pytest


def _settings(**overrides: object):
    from app.settings import Settings

    values = {"deepseek_api_key": "test-deepseek-key"}
    values.update(overrides)
    return Settings(**values)


def _segments():
    from app.services.proofread_deepseek import ProofreadSegment

    return [
        ProofreadSegment(
            id="seg-0001",
            start_seconds=0.0,
            end_seconds=1.5,
            text="你好，世界。",
            translated_text="こんにちは、世界。",
        ),
        ProofreadSegment(
            id="seg-0002",
            start_seconds=1.5,
            end_seconds=3.0,
            text="谢谢。",
            translated_text="ありがとう。",
        ),
    ]


def _response_for(segments) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "corrections": [
                                    {
                                        "id": segment.id,
                                        "start_seconds": segment.start_seconds,
                                        "end_seconds": segment.end_seconds,
                                        "text": segment.text,
                                        "translated_text": segment.translated_text,
                                    }
                                    for segment in segments
                                ]
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 24},
        },
    )


def test_proofread_segments_sends_non_thinking_json_request_and_returns_validated_rows() -> None:
    # Given: a fake OpenAI-compatible endpoint and two adjacent bilingual rows.
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _response_for(_segments())

    from app.services.proofread_deepseek import DeepSeekProofreader

    client = httpx.Client(transport=httpx.MockTransport(handler))
    proofreader = DeepSeekProofreader(_settings(), client=client)

    # When: the provider proofreads the rows.
    result = proofreader.proofread_segments(_segments())

    # Then: it preserves the source-time rows and makes a constrained JSON-mode request.
    assert result.segments == _segments()
    assert result.batch_audits[0].model == "deepseek-v4-flash"
    assert result.batch_audits[0].token_usage == {"prompt_tokens": 12, "completion_tokens": 24}
    assert "test-deepseek-key" not in repr(result.batch_audits)
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["authorization"] == "Bearer test-deepseek-key"
    body = json.loads(request.content)
    assert body["model"] == "deepseek-v4-flash"
    assert body["stream"] is False
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert "JSON" in body["messages"][0]["content"]
    assert "readonly_context_before" in body["messages"][1]["content"]


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_proofread_segments_retries_transient_http_statuses(status_code: int) -> None:
    # Given: a transient failure followed by a valid DeepSeek response.
    attempts = 0
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(status_code)
        return _response_for(_segments())

    from app.services.proofread_deepseek import DeepSeekProofreader

    proofreader = DeepSeekProofreader(
        _settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=slept.append,
        random_float=lambda: 0.0,
    )

    # When: the provider sees the transient status.
    result = proofreader.proofread_segments(_segments())

    # Then: it retries once with bounded backoff and returns the validated response.
    assert result.segments == _segments()
    assert attempts == 2
    assert slept == [0.5]
    assert result.batch_audits[0].attempt_count == 2


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [(401, "proofread_auth_failed"), (402, "proofread_billing_failed"), (422, "proofread_http_error")],
)
def test_proofread_segments_does_not_retry_permanent_http_statuses(status_code: int, expected_code: str) -> None:
    # Given: a non-retryable provider error.
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code)

    from app.services.proofread_deepseek import DeepSeekProofreader, ProofreadFailure

    proofreader = DeepSeekProofreader(
        _settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    # When: proofreading reaches the permanent error.
    with pytest.raises(ProofreadFailure) as raised:
        proofreader.proofread_segments(_segments())

    # Then: it reports a safe failure without another request or secret leakage.
    assert attempts == 1
    assert raised.value.code == expected_code
    assert "test-deepseek-key" not in str(raised.value)


def test_proofread_segments_exhausts_timeout_retries_without_leaking_key() -> None:
    # Given: a provider transport that times out on every attempt.
    attempts = 0
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timed out", request=request)

    from app.services.proofread_deepseek import DeepSeekProofreader, ProofreadFailure

    proofreader = DeepSeekProofreader(
        _settings(deepseek_max_retries=2),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=slept.append,
        random_float=lambda: 0.0,
    )

    # When: every request times out.
    with pytest.raises(ProofreadFailure) as raised:
        proofreader.proofread_segments(_segments())

    # Then: retries are bounded and the failure is safe to expose.
    assert attempts == 3
    assert slept == [0.5, 1.0]
    assert raised.value.code == "proofread_timeout"
    assert "test-deepseek-key" not in str(raised.value)


def test_proofread_segments_reports_exhausted_rate_limit_without_leaking_key() -> None:
    # Given: every allowed attempt receives a rate-limit response.
    from app.services.proofread_deepseek import DeepSeekProofreader, ProofreadFailure

    proofreader = DeepSeekProofreader(
        _settings(deepseek_max_retries=1),
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429))),
        sleep=lambda seconds: None,
        random_float=lambda: 0.0,
    )

    # When / Then: retry remains bounded and callers receive a stable rate-limit code.
    with pytest.raises(ProofreadFailure) as raised:
        proofreader.proofread_segments(_segments())
    assert raised.value.code == "proofread_rate_limit"
    assert "test-deepseek-key" not in str(raised.value)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not-json",
        '{"corrections": []}',
        '{"corrections": [{"id": "seg-0002", "start_seconds": 1.5, "end_seconds": 3.0, "text": "谢谢。", "translated_text": "ありがとう。"}, {"id": "seg-0001", "start_seconds": 0.0, "end_seconds": 1.5, "text": "你好，世界。", "translated_text": "こんにちは、世界。"}]}',
        '{"corrections": [{"id": "seg-0001", "start_seconds": 0.1, "end_seconds": 1.5, "text": "你好，世界。", "translated_text": "こんにちは、世界。"}, {"id": "seg-0002", "start_seconds": 1.5, "end_seconds": 3.0, "text": "谢谢。", "translated_text": "ありがとう。"}]}',
        '{"corrections": [{"id": "seg-0001", "start_seconds": 0.0, "end_seconds": 1.5, "text": "", "translated_text": "こんにちは、世界。"}, {"id": "seg-0002", "start_seconds": 1.5, "end_seconds": 3.0, "text": "谢谢。", "translated_text": "ありがとう。"}]}',
    ],
)
def test_proofread_segments_rejects_invalid_json_without_retrying(content: str) -> None:
    # Given: one malformed or contract-breaking JSON response.
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    from app.services.proofread_deepseek import DeepSeekProofreader, ProofreadFailure

    proofreader = DeepSeekProofreader(
        _settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    # When: the provider returns invalid correction JSON.
    with pytest.raises(ProofreadFailure) as raised:
        proofreader.proofread_segments(_segments())

    # Then: the response is rejected immediately rather than silently accepted or retried.
    assert attempts == 1
    assert raised.value.code == "proofread_invalid_response"


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("id", None),
        ("id", []),
        ("id", {}),
        ("id", 1),
        ("start_seconds", None),
        ("start_seconds", True),
        ("start_seconds", float("nan")),
        ("start_seconds", float("inf")),
        ("end_seconds", []),
        ("end_seconds", False),
        ("end_seconds", float("-inf")),
        ("text", None),
        ("translated_text", {}),
    ],
)
def test_proofread_segments_rejects_schema_invalid_raw_json_types(
    field: str, invalid_value: object
) -> None:
    # Given: a provider response with a raw JSON value of the wrong schema type.
    rows = [
        {
            "id": segment.id,
            "start_seconds": segment.start_seconds,
            "end_seconds": segment.end_seconds,
            "text": segment.text,
            "translated_text": segment.translated_text,
        }
        for segment in _segments()
    ]
    rows[0][field] = invalid_value

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps({"corrections": rows})}}]}
        )

    from app.services.proofread_deepseek import DeepSeekProofreader, ProofreadFailure

    proofreader = DeepSeekProofreader(
        _settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    # When: the correction response is parsed.
    with pytest.raises(ProofreadFailure) as raised:
        proofreader.proofread_segments(_segments())

    # Then: it is rejected rather than coerced into a valid subtitle row.
    assert raised.value.code == "proofread_invalid_response"


def test_proofread_segments_requires_configured_server_side_key() -> None:
    # Given: an operator has not configured the server-side DeepSeek key.
    from app.services.proofread_deepseek import DeepSeekProofreader, ProofreadFailure

    proofreader = DeepSeekProofreader(_settings(deepseek_api_key=None))

    # When: the proofread step is requested.
    with pytest.raises(ProofreadFailure) as raised:
        proofreader.proofread_segments(_segments())

    # Then: the required quality gate fails before sending any request.
    assert raised.value.code == "missing_api_key"
