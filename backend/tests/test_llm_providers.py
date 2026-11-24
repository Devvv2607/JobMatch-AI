"""The HTTP adapter, exercised through httpx.MockTransport. No request leaves the process."""

import json
from collections.abc import Callable

import httpx
import pytest

from app.core.config import Settings
from app.core.db import SessionLocal
from app.core.llm import build_providers
from app.core.llm.cache import PostgresLLMCache
from app.core.llm.providers import OpenAICompatProvider
from app.core.llm.types import LLMResult, Message, ProviderError

MESSAGES: list[Message] = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "SECRET RESUME TEXT"},
]


def provider_with(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        name="groq",
        model="test-model",
        base_url="https://llm.invalid/openai/v1/",
        api_key="test-key",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        timeout_seconds=5,
    )


async def call(provider: OpenAICompatProvider, json_mode: bool = False) -> object:
    return await provider.complete(MESSAGES, temperature=0, max_tokens=64, json_mode=json_mode)


async def test_sends_an_openai_style_request_and_parses_the_reply() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Hello."}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    completion = await provider_with(handler).complete(
        MESSAGES, temperature=0, max_tokens=64, json_mode=True
    )

    assert (completion.text, completion.prompt_tokens, completion.completion_tokens) == (
        "Hello.",
        12,
        3,
    )
    request = seen[0]
    assert str(request.url) == "https://llm.invalid/openai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    payload = json.loads(request.content)
    assert payload["model"] == "test-model"
    assert payload["temperature"] == 0
    assert payload["messages"] == MESSAGES
    assert payload["response_format"] == {"type": "json_object"}


async def test_json_mode_is_off_by_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "response_format" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    completion = await provider_with(handler).complete(
        MESSAGES, temperature=0, max_tokens=64, json_mode=False
    )
    assert completion.prompt_tokens == 0  # usage block is optional


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(429, True), (500, True), (503, True), (400, False), (401, False), (404, False)],
)
async def test_http_errors_are_classified(status: int, retryable: bool) -> None:
    provider = provider_with(lambda _: httpx.Response(status, text="SECRET RESUME TEXT echoed"))

    with pytest.raises(ProviderError) as excinfo:
        await call(provider)

    assert excinfo.value.retryable is retryable
    assert str(excinfo.value) == f"groq: HTTP {status}"  # the response body is never included


async def test_retry_after_header_is_parsed() -> None:
    provider = provider_with(lambda _: httpx.Response(429, headers={"retry-after": "7"}))
    with pytest.raises(ProviderError) as excinfo:
        await call(provider)
    assert excinfo.value.retry_after == 7.0


async def test_timeouts_and_connection_errors_are_retryable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    for handler in (timeout, refused):
        with pytest.raises(ProviderError) as excinfo:
            await call(provider_with(handler))
        assert excinfo.value.retryable is True


@pytest.mark.parametrize(
    "body",
    [{}, {"choices": []}, {"choices": [{"message": {"content": "   "}}]}, {"choices": [{}]}],
)
async def test_malformed_or_empty_replies_are_retryable_errors(body: dict[str, object]) -> None:
    provider = provider_with(lambda _: httpx.Response(200, json=body))
    with pytest.raises(ProviderError) as excinfo:
        await call(provider)
    assert excinfo.value.retryable is True


async def test_provider_chain_follows_the_configured_order_and_skips_missing_keys() -> None:
    async with httpx.AsyncClient() as http:
        none = build_providers(Settings(groq_api_key="", gemini_api_key=""), http)
        assert none == []

        settings = Settings(
            llm_provider_order="gemini, groq, ollama",
            groq_api_key="g-key",
            gemini_api_key="",
            ollama_enabled=True,
        )
        chain = build_providers(settings, http)
        assert [(p.name, p.model) for p in chain] == [
            ("groq", settings.groq_model),
            ("ollama", settings.ollama_model),
        ]

        with pytest.raises(ValueError, match="Unknown LLM provider"):
            build_providers(Settings(llm_provider_order="groq,openai"), http)


async def test_postgres_cache_round_trips_and_tolerates_duplicate_writes() -> None:
    cache = PostgresLLMCache(SessionLocal)
    result = LLMResult(
        text="cached answer",
        provider="groq",
        model="test-model",
        prompt_tokens=9,
        completion_tokens=4,
        cached=False,
    )

    assert await cache.get("k" * 64) is None
    await cache.put("k" * 64, result, prompt_name="explain_match", prompt_version=1)
    await cache.put("k" * 64, result, prompt_name="explain_match", prompt_version=1)

    hit = await cache.get("k" * 64)
    assert hit is not None
    assert (hit.text, hit.provider, hit.model, hit.cached) == (
        "cached answer",
        "groq",
        "test-model",
        True,
    )
    assert (hit.prompt_tokens, hit.completion_tokens) == (9, 4)


async def test_reasoning_effort_is_sent_only_when_configured() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    plain = provider_with(handler)
    effort = OpenAICompatProvider(
        name="groq",
        model="qwen/qwen3.8-27b",
        base_url="https://llm.invalid/openai/v1/",
        api_key="test-key",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        timeout_seconds=5,
        reasoning_effort="none",
    )
    await call(plain)
    await call(effort)
    assert "reasoning_effort" not in seen[0]
    assert seen[1]["reasoning_effort"] == "none"


async def test_the_match_sentence_client_uses_the_fast_groq_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.search as search_api
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    monkeypatch.setattr(search_api, "_llm", None)
    client = await search_api.get_llm_client()
    groq = next(p for p in client._providers if p.name == "groq")
    assert groq.model == get_settings().groq_fast_model
    assert groq._reasoning_effort == get_settings().groq_fast_reasoning_effort  # type: ignore[attr-defined]
    await search_api.close_search_resources()
