"""The single entry point for LLM calls.

Handles, in order: cache lookup, per-provider retry with exponential backoff and jitter
on retryable failures, fallback to the next provider, schema validation with a bounded
repair loop, cache write, and token/latency logging. Prompt and response text are never
logged.
"""

import asyncio
import hashlib
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Sequence

from pydantic import BaseModel, ValidationError

from app.core.llm.prompts import Prompt, load_prompt
from app.core.llm.types import (
    Completion,
    LLMCache,
    LLMProvider,
    LLMResult,
    LLMSchemaError,
    LLMUnavailableError,
    Message,
    ProviderError,
)
from app.core.metrics import LLM_CACHE_HITS, LLM_CALLS, LLM_DURATION, LLM_TOKENS

logger = logging.getLogger(__name__)

_SCHEMA_INSTRUCTION = "\n\nReply with a single JSON object that matches this JSON schema:\n"


class LLMClient:
    def __init__(
        self,
        providers: Sequence[LLMProvider],
        cache: LLMCache,
        *,
        max_retries: int,
        repair_attempts: int,
        backoff_base_seconds: float = 0.5,
        backoff_cap_seconds: float = 8.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._providers = list(providers)
        self._cache = cache
        self._max_retries = max_retries
        self._repair_attempts = repair_attempts
        self._backoff_base = backoff_base_seconds
        self._backoff_cap = backoff_cap_seconds
        self._sleep = sleep
        self._rng = rng

    async def complete(
        self,
        prompt: Prompt,
        user_content: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        use_cache: bool = True,
    ) -> LLMResult:
        """Free-text completion."""
        messages = _messages(prompt.system, user_content)
        cacheable = use_cache and temperature == 0.0
        if cacheable and (hit := await self._cache_lookup(prompt, messages, max_tokens)):
            return hit
        provider, completion = await self._call_chain(
            prompt, messages, temperature=temperature, max_tokens=max_tokens, json_mode=False
        )
        result = _result(provider, completion)
        if cacheable:
            await self._cache_store(prompt, messages, max_tokens, result)
        return result

    async def complete_structured[T: BaseModel](
        self,
        prompt: Prompt,
        user_content: str,
        schema: type[T],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        use_cache: bool = True,
    ) -> tuple[T, LLMResult]:
        """Completion parsed into `schema`. Raises LLMSchemaError if the output cannot be
        made valid within the repair budget; unvalidated output is never returned."""
        system = prompt.system + _SCHEMA_INSTRUCTION + json.dumps(schema.model_json_schema())
        messages = _messages(system, user_content)
        cacheable = use_cache and temperature == 0.0

        if cacheable and (hit := await self._cache_lookup(prompt, messages, max_tokens)):
            try:
                return _parse(hit.text, schema), hit
            except ValidationError:
                pass  # schema changed without a prompt version bump: treat as a miss

        provider, completion = await self._call_chain(
            prompt, messages, temperature=temperature, max_tokens=max_tokens, json_mode=True
        )
        prompt_tokens, completion_tokens = completion.prompt_tokens, completion.completion_tokens
        repairs = 0
        while True:
            try:
                parsed = _parse(completion.text, schema)
                break
            except ValidationError as exc:
                if repairs >= self._repair_attempts:
                    logger.warning(
                        "llm output failed schema validation",
                        extra={
                            "prompt": prompt.name,
                            "prompt_version": prompt.version,
                            "provider": provider.name,
                            "repairs": repairs,
                        },
                    )
                    raise LLMSchemaError(
                        f"{prompt.name} v{prompt.version}: output did not match "
                        f"{schema.__name__} after {repairs} repair attempts"
                    ) from exc
                repairs += 1
                repair_messages: list[Message] = [
                    *messages,
                    {"role": "assistant", "content": completion.text},
                    {"role": "user", "content": _repair_request(exc)},
                ]
                try:
                    completion = await self._call_provider(
                        provider,
                        prompt,
                        repair_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=True,
                    )
                except ProviderError as provider_exc:
                    raise LLMUnavailableError(str(provider_exc)) from provider_exc
                prompt_tokens += completion.prompt_tokens
                completion_tokens += completion.completion_tokens

        result = LLMResult(
            text=completion.text,
            provider=provider.name,
            model=provider.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached=False,
        )
        if cacheable:
            await self._cache_store(prompt, messages, max_tokens, result)
        return parsed, result

    async def _call_chain(
        self,
        prompt: Prompt,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> tuple[LLMProvider, Completion]:
        failures: list[str] = []
        for provider in self._providers:
            try:
                completion = await self._call_provider(
                    provider,
                    prompt,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
                return provider, completion
            except ProviderError as exc:
                failures.append(str(exc))
        raise LLMUnavailableError(
            "all LLM providers failed: " + ("; ".join(failures) or "none configured")
        )

    async def _call_provider(
        self,
        provider: LLMProvider,
        prompt: Prompt,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Completion:
        """One provider, retried on retryable failures. Raises the last ProviderError."""
        attempt = 0
        while True:
            start = time.perf_counter()
            log = {
                "provider": provider.name,
                "model": provider.model,
                "prompt": prompt.name,
                "prompt_version": prompt.version,
                "attempt": attempt + 1,
            }
            try:
                completion = await provider.complete(
                    messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
                )
            except ProviderError as exc:
                duration = time.perf_counter() - start
                LLM_CALLS.labels(provider.name, provider.model, "error").inc()
                logger.warning(
                    "llm call failed",
                    extra={
                        **log,
                        "duration_ms": round(duration * 1000, 1),
                        "error": str(exc),
                        "retryable": exc.retryable,
                    },
                )
                if not exc.retryable or attempt >= self._max_retries:
                    raise
                await self._sleep(self._backoff(attempt, exc.retry_after))
                attempt += 1
                continue

            duration = time.perf_counter() - start
            LLM_CALLS.labels(provider.name, provider.model, "ok").inc()
            LLM_DURATION.labels(provider.name, provider.model).observe(duration)
            LLM_TOKENS.labels(provider.name, provider.model, "prompt").inc(completion.prompt_tokens)
            LLM_TOKENS.labels(provider.name, provider.model, "completion").inc(
                completion.completion_tokens
            )
            logger.info(
                "llm call",
                extra={
                    **log,
                    "duration_ms": round(duration * 1000, 1),
                    "prompt_tokens": completion.prompt_tokens,
                    "completion_tokens": completion.completion_tokens,
                },
            )
            return completion

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self._backoff_cap)
        # Full jitter: uniform between 0 and the exponential ceiling.
        return self._rng() * min(self._backoff_cap, self._backoff_base * 2.0**attempt)

    async def _cache_lookup(
        self, prompt: Prompt, messages: list[Message], max_tokens: int
    ) -> LLMResult | None:
        for provider in self._providers:
            hit = await self._cache.get(_cache_key(prompt, provider.model, messages, max_tokens))
            if hit is not None:
                LLM_CACHE_HITS.inc()
                logger.info(
                    "llm cache hit",
                    extra={
                        "prompt": prompt.name,
                        "prompt_version": prompt.version,
                        "model": provider.model,
                    },
                )
                return hit
        return None

    async def _cache_store(
        self, prompt: Prompt, messages: list[Message], max_tokens: int, result: LLMResult
    ) -> None:
        await self._cache.put(
            _cache_key(prompt, result.model, messages, max_tokens),
            result,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
        )


def _messages(system: str, user_content: str) -> list[Message]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user_content}]


def _result(provider: LLMProvider, completion: Completion) -> LLMResult:
    return LLMResult(
        text=completion.text,
        provider=provider.name,
        model=provider.model,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        cached=False,
    )


def _cache_key(prompt: Prompt, model: str, messages: list[Message], max_tokens: int) -> str:
    material = json.dumps(
        [prompt.name, prompt.version, model, messages, max_tokens], sort_keys=True
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _parse[T: BaseModel](text: str, schema: type[T]) -> T:
    """Validates the JSON object in `text`, tolerating code fences or stray prose."""
    start, end = text.find("{"), text.rfind("}")
    candidate = text[start : end + 1] if start != -1 and end > start else text
    return schema.model_validate_json(candidate)


def _repair_request(exc: ValidationError) -> str:
    errors = "\n".join(
        f"- {'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
        for e in exc.errors(include_url=False, include_input=False)
    )
    return f"{load_prompt('schema_repair', 1).system}\n{errors}"
