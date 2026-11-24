"""Startup model check against a mocked /models endpoint. No network."""

from collections.abc import Callable, Iterator

import httpx
import pytest

from app.core.llm import availability
from app.core.llm.availability import ProviderModels, check_models, configured, is_unavailable
from app.core.llm.client import LLMClient
from app.core.llm.types import Completion, LLMUnavailableError
from tests.test_llm_client import PROMPT, MemoryCache, StubProvider

GROQ = ProviderModels(
    "groq",
    "https://llm.invalid/openai/v1",
    "test-key",
    frozenset({"openai/gpt-oss-120b", "qwen/qwen3.8-27b"}),
)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    availability.reset()
    yield
    availability.reset()


def http(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def listing(*ids: str) -> httpx.Response:
    return httpx.Response(200, json={"object": "list", "data": [{"id": i} for i in ids]})


async def test_listed_models_stay_available_and_missing_ones_are_marked(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return listing("openai/gpt-oss-120b", "openai/gpt-oss-20b")

    await check_models([GROQ], http(handler))
    assert str(seen[0].url) == "https://llm.invalid/openai/v1/models"
    assert seen[0].headers["Authorization"] == "Bearer test-key"
    assert not is_unavailable("groq", "openai/gpt-oss-120b")
    assert is_unavailable("groq", "qwen/qwen3.8-27b")
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1 and errors[0].model == "qwen/qwen3.8-27b"  # type: ignore[attr-defined]


async def test_a_failing_models_endpoint_disables_nothing() -> None:
    for handler in (
        lambda _: httpx.Response(500),
        lambda _: httpx.Response(200, content=b"not json"),
        lambda _: listing(),  # an empty list is not trusted either
    ):
        await check_models([GROQ], http(handler))
        assert not is_unavailable("groq", "qwen/qwen3.8-27b")


async def test_gemini_style_ids_with_a_models_prefix_match() -> None:
    gemini = ProviderModels(
        "gemini", "https://g.invalid/v1beta/openai", "k", frozenset({"gemini-x"})
    )
    await check_models([gemini], http(lambda _: listing("models/gemini-x")))
    assert not is_unavailable("gemini", "gemini-x")


async def test_a_model_found_again_on_a_later_check_is_re_enabled() -> None:
    await check_models([GROQ], http(lambda _: listing("openai/gpt-oss-120b")))
    assert is_unavailable("groq", "qwen/qwen3.8-27b")
    await check_models([GROQ], http(lambda _: listing("openai/gpt-oss-120b", "qwen/qwen3.8-27b")))
    assert not is_unavailable("groq", "qwen/qwen3.8-27b")


async def test_the_client_routes_around_an_unavailable_model() -> None:
    groq = StubProvider("groq", [])  # would fail the test if called (no scripted outcomes)
    ollama = StubProvider(
        "ollama", [Completion(text="from ollama", prompt_tokens=1, completion_tokens=1)]
    )
    await check_models(
        [ProviderModels("groq", "https://llm.invalid", "k", frozenset({groq.model}))],
        http(lambda _: listing("something-else")),
    )
    client = LLMClient([groq, ollama], MemoryCache(), max_retries=0, repair_attempts=0)
    result = await client.complete(PROMPT, "hi", data_class="personal")
    assert result.provider == "ollama" and groq.calls == []

    alone = LLMClient([groq], MemoryCache(), max_retries=0, repair_attempts=0)
    with pytest.raises(LLMUnavailableError):
        await alone.complete(PROMPT, "hi", data_class="personal")


def test_only_enabled_providers_and_both_groq_models_are_checked() -> None:
    from app.core.config import get_settings

    settings = get_settings().model_copy(
        update={"groq_api_key": "k", "gemini_api_key": "", "ollama_enabled": False}
    )
    [groq] = configured(settings)
    assert groq.name == "groq"
    assert groq.models == {settings.groq_model, settings.groq_fast_model}
