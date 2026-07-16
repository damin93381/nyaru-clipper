from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass
from typing import Callable, TypedDict

import httpx
from pydantic import SecretStr

from app.settings import Settings

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 503})
_MAX_RESPONSE_BYTES = 1_000_000
_MAX_TEXT_CHARS = 4_000


class _TokenUsage(TypedDict, total=False):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class ProofreadSegment:
    """One source-timestamped bilingual subtitle row eligible for constrained editing."""

    id: str
    start_seconds: float
    end_seconds: float
    text: str
    translated_text: str


@dataclass(frozen=True, slots=True)
class ProofreadBatchAudit:
    """Non-secret metadata for one validated DeepSeek correction batch."""

    batch_index: int
    model: str
    attempt_count: int
    elapsed_seconds: float
    changed_segment_count: int
    token_usage: _TokenUsage


@dataclass(frozen=True, slots=True)
class ProofreadResult:
    """Validated proofread rows plus safe audit data for later artifact persistence."""

    segments: list[ProofreadSegment]
    batch_audits: list[ProofreadBatchAudit]


@dataclass(frozen=True, slots=True)
class ProofreadFailure(RuntimeError):
    """A safe, stable failure emitted by the external proofread boundary."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class DeepSeekProofreader:
    """Call DeepSeek JSON mode and accept only timestamp-preserving correction rows."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_float: Callable[[], float] = random.random,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.deepseek_request_timeout_seconds)
        self._sleep = sleep
        self._random_float = random_float

    def proofread_segments(self, segments: list[ProofreadSegment]) -> ProofreadResult:
        """Proofread bounded contiguous rows, retaining their identity and source timing."""
        api_key = self._settings.deepseek_api_key
        if api_key is None:
            raise ProofreadFailure(
                code="missing_api_key",
                message="DeepSeek proofreading requires APP_DEEPSEEK_API_KEY before retrying translation.",
            )
        if not segments:
            return ProofreadResult(segments=[], batch_audits=[])

        corrected_segments: list[ProofreadSegment] = []
        batch_audits: list[ProofreadBatchAudit] = []
        batch_size = self._settings.deepseek_max_segments_per_request
        for batch_index, start in enumerate(range(0, len(segments), batch_size)):
            batch = segments[start : start + batch_size]
            context_before = segments[start - 1 : start]
            context_after = segments[start + batch_size : start + batch_size + 1]
            corrected_batch, audit = self._proofread_batch(
                batch=batch,
                context_before=context_before,
                context_after=context_after,
                batch_index=batch_index,
                api_key=api_key,
            )
            corrected_segments.extend(corrected_batch)
            batch_audits.append(audit)
        return ProofreadResult(segments=corrected_segments, batch_audits=batch_audits)

    def _proofread_batch(
        self,
        *,
        batch: list[ProofreadSegment],
        context_before: list[ProofreadSegment],
        context_after: list[ProofreadSegment],
        batch_index: int,
        api_key: SecretStr,
    ) -> tuple[list[ProofreadSegment], ProofreadBatchAudit]:
        started_at = time.perf_counter()
        attempts = 0
        while True:
            attempts += 1
            try:
                response = self._client.post(
                    f"{self._settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
                    json=self._request_payload(
                        batch=batch,
                        context_before=context_before,
                        context_after=context_after,
                    ),
                )
            except httpx.TimeoutException as exc:
                if self._should_retry(attempts):
                    self._sleep(self._retry_delay(attempts))
                    continue
                raise ProofreadFailure(
                    code="proofread_timeout",
                    message="DeepSeek proofreading timed out after bounded retries. Retry translation later.",
                ) from exc

            if response.status_code in _RETRYABLE_STATUS_CODES:
                if self._should_retry(attempts):
                    self._sleep(self._retry_delay(attempts))
                    continue
                if response.status_code == 429:
                    raise ProofreadFailure(
                        code="proofread_rate_limit",
                        message="DeepSeek proofreading remained rate-limited after bounded retries.",
                    )
                raise ProofreadFailure(
                    code="proofread_transient_exhausted",
                    message="DeepSeek proofreading remained temporarily unavailable after bounded retries.",
                )
            if response.status_code >= 400:
                if response.status_code == 401:
                    raise ProofreadFailure(
                        code="proofread_auth_failed",
                        message="DeepSeek rejected the proofreading credential; update the operator-side configuration.",
                    )
                if response.status_code == 402:
                    raise ProofreadFailure(
                        code="proofread_billing_failed",
                        message="DeepSeek billing must be resolved before retrying translation.",
                    )
                raise ProofreadFailure(
                    code="proofread_http_error",
                    message="DeepSeek rejected the proofreading request; resolve the operator-side issue before retrying.",
                )

            corrected_batch, token_usage = self._parse_response(response, batch)
            changed_segment_count = sum(
                corrected != original for corrected, original in zip(corrected_batch, batch, strict=True)
            )
            return corrected_batch, ProofreadBatchAudit(
                batch_index=batch_index,
                model=self._settings.deepseek_model,
                attempt_count=attempts,
                elapsed_seconds=round(time.perf_counter() - started_at, 3),
                changed_segment_count=changed_segment_count,
                token_usage=token_usage,
            )

    def _request_payload(
        self,
        *,
        batch: list[ProofreadSegment],
        context_before: list[ProofreadSegment],
        context_after: list[ProofreadSegment],
    ) -> dict[str, object]:
        return {
            "model": self._settings.deepseek_model,
            "stream": False,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return a JSON object only. Correct bilingual subtitle rows conservatively; preserve "
                        "each requested id, timestamps, order, and count exactly."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "readonly_context_before": self._wire_rows(context_before),
                            "requested_rows": self._wire_rows(batch),
                            "readonly_context_after": self._wire_rows(context_after),
                            "response_schema": {
                                "corrections": [
                                    {
                                        "id": "requested id",
                                        "start_seconds": "unchanged number",
                                        "end_seconds": "unchanged number",
                                        "text": "non-empty Chinese text",
                                        "translated_text": "non-empty Japanese text",
                                    }
                                ]
                            },
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
        }

    @staticmethod
    def _wire_rows(segments: list[ProofreadSegment]) -> list[dict[str, str | float]]:
        return [
            {
                "id": segment.id,
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "text": segment.text,
                "translated_text": segment.translated_text,
            }
            for segment in segments
        ]

    def _parse_response(
        self, response: httpx.Response, requested_segments: list[ProofreadSegment]
    ) -> tuple[list[ProofreadSegment], _TokenUsage]:
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise self._invalid_response()
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            corrections = json.loads(content)
        except (IndexError, KeyError, TypeError, json.JSONDecodeError):
            raise self._invalid_response() from None
        if not isinstance(corrections, dict):
            raise self._invalid_response()
        raw_rows = corrections.get("corrections")
        if not isinstance(raw_rows, list) or len(raw_rows) != len(requested_segments):
            raise self._invalid_response()

        corrected_segments: list[ProofreadSegment] = []
        for raw_row, requested in zip(raw_rows, requested_segments, strict=True):
            if not isinstance(raw_row, dict):
                raise self._invalid_response()
            try:
                raw_id = raw_row["id"]
                raw_start_seconds = raw_row["start_seconds"]
                raw_end_seconds = raw_row["end_seconds"]
                raw_text = raw_row["text"]
                raw_translated_text = raw_row["translated_text"]
            except KeyError:
                raise self._invalid_response() from None
            if (
                not isinstance(raw_id, str)
                or not self._is_finite_json_number(raw_start_seconds)
                or not self._is_finite_json_number(raw_end_seconds)
                or not isinstance(raw_text, str)
                or not isinstance(raw_translated_text, str)
            ):
                raise self._invalid_response()
            corrected = ProofreadSegment(
                id=raw_id,
                start_seconds=float(raw_start_seconds),
                end_seconds=float(raw_end_seconds),
                text=raw_text.strip(),
                translated_text=raw_translated_text.strip(),
            )
            if (
                corrected.id != requested.id
                or corrected.start_seconds != requested.start_seconds
                or corrected.end_seconds != requested.end_seconds
                or not corrected.text
                or not corrected.translated_text
                or len(corrected.text) > _MAX_TEXT_CHARS
                or len(corrected.translated_text) > _MAX_TEXT_CHARS
            ):
                raise self._invalid_response()
            corrected_segments.append(corrected)
        return corrected_segments, self._token_usage(payload)

    @staticmethod
    def _is_finite_json_number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    @staticmethod
    def _token_usage(payload: object) -> _TokenUsage:
        if not isinstance(payload, dict):
            return {}
        raw_usage = payload.get("usage")
        if not isinstance(raw_usage, dict):
            return {}
        usage: _TokenUsage = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = raw_usage.get(key)
            if isinstance(value, int):
                usage[key] = value
        return usage

    def _should_retry(self, attempts: int) -> bool:
        return attempts <= self._settings.deepseek_max_retries

    def _retry_delay(self, attempts: int) -> float:
        return min(8.0, 0.5 * (2 ** (attempts - 1))) + (self._random_float() * 0.25)

    @staticmethod
    def _invalid_response() -> ProofreadFailure:
        return ProofreadFailure("proofread_invalid_response", "DeepSeek returned an invalid proofreading response.")
