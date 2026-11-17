"""LLM client behaviour against scripted stub providers. Nothing here touches a network."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from app.core.llm.client import LLMClient
from app.core.llm.prompts import Prompt, load_prompt
from app.core.llm.types import (
    Completion,
    LLMResult,
    LLMSchemaError,
    LLMUnavailableError,
    Message,
    ProviderError,
)

PROMPT = Prompt(name="explain_match", version=1, system="Explain the match in one sentence.")


class StubProvider:
    """Returns or raises the scripted outcomes in order, recording every call."""

    def __init__(self, name: str, outcomes: list[Completion | ProviderError]) -> None:
        self.name = name
        self.model = f"{name}-model"
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    async def complete(
        self, messages: list[Message], *, temperature: float, max_tokens: int, json_mode: bool
    ) -> Completion:
        self.calls.append({"messages": messages, "json_mode": json_mode})
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, ProviderError):
            raise outcome
        return outcome


class MemoryCache:
    def __init__(self) -> None:
        self.entries: dict[str, LLMResult] = {}

    async def get(self, key: str) -> LLMResult | None:
        hit = self.entries.get(key)
        return None if hit is None else LLMResult(**{**hit.__dict__, "cached": True})

    async def put(
        self, key: str, result: LLMResult, *, prompt_name: str, prompt_version: int
    ) -> None:
        self.entries[key] = result


class Sleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def ok(
    text: str = "A fine answer.", prompt_tokens: int = 10, completion_tokens: int = 5
) -> Completion:
    return Completion(text=text, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)


def rate_limited(retry_after: float | None = None) -> ProviderError:
    return ProviderError("HTTP 429", retryable=True, retry_after=retry_after)


def server_error() -> ProviderError:
    return ProviderError("HTTP 503", retryable=True)


def bad_request() -> ProviderError:
    return ProviderError("HTTP 400", retryable=False)


def make_client(
    *providers: StubProvider,
    cache: MemoryCache | None = None,
    sleeper: Sleeper | None = None,
    max_retries: int = 3,
    repair_attempts: int = 2,
) -> LLMClient:
    return LLMClient(
        providers,
        cache or MemoryCache(),
        max_retries=max_retries,
        repair_attempts=repair_attempts,
        backoff_base_seconds=0.5,
        backoff_cap_seconds=8.0,
        sleep=sleeper or Sleeper(),
        rng=lambda: 1.0,  # deterministic: always the top of the jitter range
    )


class Verdict(BaseModel):
    label: str
    score: int


# --- retry ---------------------------------------------------------------------------


async def test_retries_retryable_failures_with_exponential_backoff() -> None:
    provider = StubProvider("groq", [rate_limited(), server_error(), ok()])
    sleeper = Sleeper()
    client = make_client(provider, sleeper=sleeper)

    result = await client.complete(PROMPT, "job text")

    assert result.text == "A fine answer."
    assert len(provider.calls) == 3
    assert sleeper.delays == [0.5, 1.0]  # base * 2**attempt, at the top of the jitter range


async def test_backoff_is_jittered_and_capped() -> None:
    provider = StubProvider("groq", [server_error()] * 6 + [ok()])
    sleeper = Sleeper()
    client = LLMClient(
        [provider],
        MemoryCache(),
        max_retries=6,
        repair_attempts=0,
        backoff_base_seconds=0.5,
        backoff_cap_seconds=8.0,
        sleep=sleeper,
        rng=lambda: 0.5,
    )

    await client.complete(PROMPT, "job text")

    # rng=0.5 halves each ceiling; the ceiling stops growing at the 8s cap.
    assert sleeper.delays == [0.25, 0.5, 1.0, 2.0, 4.0, 4.0]


async def test_retry_after_header_is_honoured_up_to_the_cap() -> None:
    provider = StubProvider("groq", [rate_limited(retry_after=2.0), rate_limited(600.0), ok()])
    sleeper = Sleeper()
    client = make_client(provider, sleeper=sleeper)

    await client.complete(PROMPT, "job text")

    assert sleeper.delays == [2.0, 8.0]


async def test_non_retryable_failure_is_not_retried() -> None:
    provider = StubProvider("groq", [bad_request(), ok()])
    sleeper = Sleeper()
    client = make_client(provider, sleeper=sleeper)

    with pytest.raises(LLMUnavailableError):
        await client.complete(PROMPT, "job text")

    assert len(provider.calls) == 1
    assert sleeper.delays == []


# --- fallback chain ------------------------------------------------------------------


async def test_falls_back_to_the_next_provider_when_retries_run_out() -> None:
    groq = StubProvider("groq", [server_error(), server_error(), server_error()])
    gemini = StubProvider("gemini", [ok("From Gemini.")])
    client = make_client(groq, gemini, max_retries=2)

    result = await client.complete(PROMPT, "job text")

    assert len(groq.calls) == 3  # first try + 2 retries
    assert len(gemini.calls) == 1
    assert (result.provider, result.model, result.text) == (
        "gemini",
        "gemini-model",
        "From Gemini.",
    )


async def test_non_retryable_failure_falls_back_immediately() -> None:
    groq = StubProvider("groq", [bad_request()])
    gemini = StubProvider("gemini", [bad_request()])
    ollama = StubProvider("ollama", [ok("From Ollama.")])
    client = make_client(groq, gemini, ollama)

    result = await client.complete(PROMPT, "job text")

    assert [len(p.calls) for p in (groq, gemini, ollama)] == [1, 1, 1]
    assert result.provider == "ollama"


async def test_raises_unavailable_when_every_provider_fails() -> None:
    groq = StubProvider("groq", [bad_request()])
    gemini = StubProvider("gemini", [server_error(), server_error()])
    client = make_client(groq, gemini, max_retries=1)

    with pytest.raises(LLMUnavailableError, match="all LLM providers failed"):
        await client.complete(PROMPT, "job text")


async def test_raises_unavailable_when_no_provider_is_configured() -> None:
    with pytest.raises(LLMUnavailableError, match="none configured"):
        await make_client().complete(PROMPT, "job text")


# --- schema validation and repair ----------------------------------------------------


async def test_valid_structured_output_is_parsed_and_requests_json_mode() -> None:
    provider = StubProvider("groq", [ok('{"label": "Strong fit", "score": 3}')])
    client = make_client(provider)

    parsed, result = await client.complete_structured(PROMPT, "job text", Verdict)

    assert parsed == Verdict(label="Strong fit", score=3)
    assert result.cached is False
    assert provider.calls[0]["json_mode"] is True
    system = provider.calls[0]["messages"][0]["content"]  # type: ignore[index]
    assert '"score"' in system  # the JSON schema is part of the instructions


async def test_json_wrapped_in_a_code_fence_is_accepted() -> None:
    provider = StubProvider("groq", [ok('```json\n{"label": "Stretch", "score": 1}\n```')])
    parsed, _ = await make_client(provider).complete_structured(PROMPT, "job text", Verdict)
    assert parsed.label == "Stretch"


async def test_invalid_output_is_repaired_with_the_validation_errors() -> None:
    provider = StubProvider(
        "groq",
        [
            ok('{"label": "Good fit", "score": "high"}', prompt_tokens=100, completion_tokens=10),
            ok('{"label": "Good fit", "score": 2}', prompt_tokens=130, completion_tokens=12),
        ],
    )
    client = make_client(provider)

    parsed, result = await client.complete_structured(PROMPT, "job text", Verdict)

    assert parsed == Verdict(label="Good fit", score=2)
    assert len(provider.calls) == 2
    repair_messages: list[Message] = provider.calls[1]["messages"]  # type: ignore[assignment]
    assert [m["role"] for m in repair_messages] == ["system", "user", "assistant", "user"]
    assert repair_messages[2]["content"] == '{"label": "Good fit", "score": "high"}'
    assert "- score:" in repair_messages[3]["content"]
    # Tokens from the failed attempt are still counted.
    assert (result.prompt_tokens, result.completion_tokens) == (230, 22)


async def test_repair_is_bounded_and_invalid_output_is_never_returned() -> None:
    provider = StubProvider("groq", [ok("not json at all")] * 5)
    cache = MemoryCache()
    client = make_client(provider, cache=cache, repair_attempts=2)

    with pytest.raises(LLMSchemaError, match="after 2 repair attempts"):
        await client.complete_structured(PROMPT, "job text", Verdict)

    assert len(provider.calls) == 3  # first try + 2 repairs, then stop
    assert cache.entries == {}


async def test_provider_failure_during_repair_is_reported_as_unavailable() -> None:
    provider = StubProvider("groq", [ok("not json"), bad_request()])
    with pytest.raises(LLMUnavailableError):
        await make_client(provider).complete_structured(PROMPT, "job text", Verdict)


# --- cache ---------------------------------------------------------------------------


async def test_identical_call_is_served_from_cache() -> None:
    provider = StubProvider("groq", [ok()])
    client = make_client(provider)

    first = await client.complete(PROMPT, "job text")
    second = await client.complete(PROMPT, "job text")

    assert len(provider.calls) == 1
    assert (first.cached, second.cached) == (False, True)
    assert second.text == first.text


async def test_cache_key_covers_prompt_version_input_and_model() -> None:
    cache = MemoryCache()
    provider = StubProvider("groq", [ok("one"), ok("two"), ok("three")])
    client = make_client(provider, cache=cache)

    await client.complete(PROMPT, "job text")
    await client.complete(Prompt(PROMPT.name, 2, PROMPT.system), "job text")  # version bump
    await client.complete(PROMPT, "different job text")  # different input
    assert len(provider.calls) == 3

    other_model = StubProvider("gemini", [ok("four")])
    await make_client(other_model, cache=cache).complete(PROMPT, "job text")
    assert len(other_model.calls) == 1
    assert len(cache.entries) == 4


async def test_a_response_cached_from_the_fallback_provider_is_reused() -> None:
    cache = MemoryCache()
    groq = StubProvider("groq", [bad_request()])
    gemini = StubProvider("gemini", [ok("From Gemini.")])
    await make_client(groq, gemini, cache=cache).complete(PROMPT, "job text")

    groq_again = StubProvider("groq", [])
    gemini_again = StubProvider("gemini", [])
    result = await make_client(groq_again, gemini_again, cache=cache).complete(PROMPT, "job text")

    assert result.cached is True
    assert result.provider == "gemini"
    assert groq_again.calls == gemini_again.calls == []


async def test_sampled_and_opted_out_calls_bypass_the_cache() -> None:
    cache = MemoryCache()
    provider = StubProvider("groq", [ok("a"), ok("b"), ok("c"), ok("d")])
    client = make_client(provider, cache=cache)

    await client.complete(PROMPT, "job text", temperature=0.7)
    await client.complete(PROMPT, "job text", temperature=0.7)
    await client.complete(PROMPT, "job text", use_cache=False)
    await client.complete(PROMPT, "job text", use_cache=False)

    assert len(provider.calls) == 4
    assert cache.entries == {}


async def test_structured_results_are_cached_and_revalidated() -> None:
    cache = MemoryCache()
    provider = StubProvider("groq", [ok('{"label": "Good fit", "score": 2}')])
    client = make_client(provider, cache=cache)

    await client.complete_structured(PROMPT, "job text", Verdict)
    parsed, result = await client.complete_structured(PROMPT, "job text", Verdict)

    assert len(provider.calls) == 1
    assert result.cached is True
    assert parsed.score == 2


# --- prompts -------------------------------------------------------------------------


def test_prompts_are_loaded_from_versioned_files(tmp_path: Path) -> None:
    (tmp_path / "explain_match").mkdir()
    (tmp_path / "explain_match" / "v1.md").write_text("First wording.\n", encoding="utf-8")
    (tmp_path / "explain_match" / "v2.md").write_text("Second wording.\n", encoding="utf-8")

    v1 = load_prompt("explain_match", 1, tmp_path)
    v2 = load_prompt("explain_match", 2, tmp_path)

    assert (v1.name, v1.version, v1.system) == ("explain_match", 1, "First wording.")
    assert v2.system == "Second wording."
    with pytest.raises(FileNotFoundError):
        load_prompt("explain_match", 3, tmp_path)
