"""Provider errors say why (owner, 2026-11-26): status, the provider's code and message
(trimmed, identifiers redacted, never the request) and whether a daily quota is hit."""

import httpx
import pytest

from app.core.llm.providers import OpenAICompatProvider
from app.core.llm.types import ProviderError


def provider(response: httpx.Response) -> OpenAICompatProvider:
    transport = httpx.MockTransport(lambda request: response)
    return OpenAICompatProvider(
        name="gemini",
        model="m",
        base_url="https://example.test/v1",
        api_key="k",
        http=httpx.AsyncClient(transport=transport),
        timeout_seconds=5,
    )


async def call(response: httpx.Response) -> ProviderError:
    with pytest.raises(ProviderError) as info:
        await provider(response).complete(
            [{"role": "user", "content": "secret prompt"}],
            temperature=0,
            max_tokens=10,
            json_mode=False,
        )
    return info.value


async def test_gemini_daily_quota_is_named_and_not_retried_today() -> None:
    body = [
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "You exceeded your current quota.",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                "quotaValue": "1000",
                            }
                        ],
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "39s"},
                ],
            }
        }
    ]
    exc = await call(httpx.Response(429, json=body))
    assert exc.status == 429 and exc.daily_cap
    assert "RESOURCE_EXHAUSTED" in exc.detail and "PerDay" in exc.detail and "1000" in exc.detail
    assert exc.retry_after == 39.0


async def test_groq_per_minute_limit_is_retryable_and_org_ids_are_redacted() -> None:
    body = {
        "error": {
            "message": "Rate limit reached for model in organization `org_01abcdefgh12` on "
            "tokens per minute (TPM): Limit 8000. Please try again in 2.5s.",
            "type": "tokens",
            "code": "rate_limit_exceeded",
        }
    }
    exc = await call(httpx.Response(429, json=body, headers={"retry-after": "3"}))
    assert exc.retryable and not exc.daily_cap and exc.retry_after == 3.0
    assert "org_01abcdefgh12" not in exc.detail and "<redacted>" in exc.detail
    assert "tokens per minute" in exc.detail


async def test_a_bad_request_never_logs_the_provider_message() -> None:
    body = {"error": {"message": "invalid input: secret prompt", "type": "invalid_request_error"}}
    exc = await call(httpx.Response(400, json=body))
    assert not exc.retryable
    assert "secret prompt" not in exc.detail and "invalid_request_error" in exc.detail


async def test_an_empty_completion_reports_the_finish_reason() -> None:
    body = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}], "usage": {}}
    exc = await call(httpx.Response(200, json=body))
    assert exc.kind == "empty" and exc.detail == "finish_reason=length"
