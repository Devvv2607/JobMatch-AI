from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

DataClass = Literal["personal", "public"]

# Which providers may receive each class of data. Fixed in code, not configuration, so a
# setting cannot route personal data to a provider that may train on it. "personal" is
# anything derived from a real person: resume text, profile, tailoring, verification,
# interview answers, agent turns with user context, and files under eval/private.
# "public" is job postings and fictional eval data. Unknown providers get nothing.
ALLOWED_PROVIDERS: dict[DataClass, frozenset[str]] = {
    "personal": frozenset({"groq", "ollama"}),
    "public": frozenset({"groq", "gemini", "ollama"}),
}


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

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        retry_after: float | None = None,
        status: int | None = None,
        kind: str = "http",
        detail: str = "",
        daily_cap: bool = False,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after
        self.status = status  # HTTP status, None for timeouts and connection errors
        self.kind = kind  # http | timeout | connection | malformed | empty
        # The provider's own error code and message (trimmed, identifiers redacted; never
        # the request), so a log says *why*: "RESOURCE_EXHAUSTED ... PerDay".
        self.detail = detail
        self.daily_cap = daily_cap  # a per-day quota: retrying today cannot succeed


class DataRoutingError(Exception):
    """A call was about to send data to a provider not allowed for its data class.

    Deliberately not a ProviderError: the fallback chain must never swallow it."""


class LLMUnavailableError(Exception):
    """Every provider in the chain failed. Callers fall back to their degraded mode."""


class LLMQuotaExhaustedError(LLMUnavailableError):
    """Every provider in the chain refused with a per-day quota: retry tomorrow."""


class LLMSchemaError(Exception):
    """The model's output still failed schema validation after the repair attempts."""
