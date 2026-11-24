"""Provider adapters.

Groq, Gemini and Ollama all expose an OpenAI-compatible chat completions endpoint,
so one adapter covers the whole fallback chain and no provider SDK is needed.
"""

import httpx

from app.core.llm.types import Completion, Message, ProviderError

_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        name: str,
        model: str,
        base_url: str,
        api_key: str,
        http: httpx.AsyncClient,
        timeout_seconds: float,
        reasoning_effort: str = "",
    ) -> None:
        self.name = name
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http
        self._timeout = timeout_seconds
        # Sent only when set: e.g. "none" turns Qwen3's thinking off on Groq.
        self._reasoning_effort = reasoning_effort

    async def complete(
        self, messages: list[Message], *, temperature: float, max_tokens: int, json_mode: bool
    ) -> Completion:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        try:
            response = await self._http.post(
                self._url, json=payload, headers=self._headers, timeout=self._timeout
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(f"{self.name}: timed out", retryable=True) from exc
        except httpx.TransportError as exc:
            raise ProviderError(f"{self.name}: connection failed", retryable=True) from exc

        if response.status_code != 200:
            # The body is not included: providers may echo the request in errors.
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}",
                retryable=response.status_code in _RETRYABLE_STATUS,
                retry_after=_retry_after(response),
            )
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.name}: malformed response", retryable=True) from exc
        if not isinstance(text, str) or not text.strip():
            raise ProviderError(f"{self.name}: empty completion", retryable=True)
        return Completion(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None
