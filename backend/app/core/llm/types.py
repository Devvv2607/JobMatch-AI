from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Completion:
    """What a provider returns for one call."""

    text: str
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cached: bool


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(
        self, messages: list[Message], *, temperature: float, max_tokens: int, json_mode: bool
    ) -> Completion: ...


class LLMCache(Protocol):
    async def get(self, key: str) -> LLMResult | None: ...

    async def put(
        self, key: str, result: LLMResult, *, prompt_name: str, prompt_version: int
    ) -> None: ...


class ProviderError(Exception):
    """A provider call failed. `retryable` separates 429/5xx/timeouts from bad requests."""

    def __init__(self, message: str, *, retryable: bool, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


class LLMUnavailableError(Exception):
    """Every provider in the chain failed. Callers fall back to their degraded mode."""


class LLMSchemaError(Exception):
    """The model's output still failed schema validation after the repair attempts."""
