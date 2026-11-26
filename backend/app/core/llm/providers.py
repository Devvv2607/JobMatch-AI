"""Provider adapters.

Groq, Gemini and Ollama all expose an OpenAI-compatible chat completions endpoint,
so one adapter covers the whole fallback chain and no provider SDK is needed.
"""

import contextlib
import re

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
            raise ProviderError(
                f"{self.name}: timed out after {self._timeout:g} s",
                retryable=True,
                kind="timeout",
                detail=type(exc).__name__,
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                f"{self.name}: connection failed",
                retryable=True,
                kind="connection",
                detail=type(exc).__name__,
            ) from exc

        if response.status_code != 200:
            detail, delay = _error_detail(response)
            retry_after = _retry_after(response)
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}",
                retryable=response.status_code in _RETRYABLE_STATUS,
                retry_after=retry_after if retry_after is not None else delay,
                status=response.status_code,
                detail=detail,
                daily_cap=response.status_code == 429 and bool(_DAILY.search(detail)),
            )
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"{self.name}: malformed response",
                retryable=True,
                status=200,
                kind="malformed",
                detail=type(exc).__name__,
            ) from exc
        if not isinstance(text, str) or not text.strip():
            finish = ""
            if isinstance(data.get("choices"), list) and data["choices"]:
                finish = str(data["choices"][0].get("finish_reason") or "")
            raise ProviderError(
                f"{self.name}: empty completion",
                retryable=True,
                status=200,
                kind="empty",
                detail=f"finish_reason={finish}",
            )
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


# A quota that resets daily: Gemini quota ids ("...PerDay...") and Groq's "tokens per
# day (TPD)" / "requests per day (RPD)".
_DAILY = re.compile(r"per ?day|\bTPD\b|\bRPD\b", re.I)
# Only these statuses' messages are kept: they describe quota, auth or a missing model.
# Others (400, 422) can quote the request, which may hold the prompt.
_SAFE_MESSAGE = frozenset({401, 403, 404, 408, 429, 500, 502, 503, 504, 529})
_REDACT = re.compile(r"\b(?:org|proj|project|user|key)[_-][A-Za-z0-9_-]{6,}|AIza[0-9A-Za-z_-]{20,}")


def _error_detail(response: httpx.Response) -> tuple[str, float | None]:
    """(the provider's error code, type/status, message and quota ids, trimmed and
    redacted; a retry delay the body gives, e.g. Gemini's RetryInfo "39s")."""
    try:
        body = response.json()
    except ValueError:
        return "", None
    if isinstance(body, list) and body:
        body = body[0]
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return "", None
    parts = [str(error.get(k)) for k in ("status", "code", "type") if error.get(k)]
    delay = None
    for item in error.get("details") or []:
        if not isinstance(item, dict):
            continue
        for violation in item.get("violations") or []:
            if isinstance(violation, dict):
                parts += [str(violation[k]) for k in ("quotaId", "quotaValue") if violation.get(k)]
        if isinstance(item.get("retryDelay"), str) and item["retryDelay"].endswith("s"):
            with contextlib.suppress(ValueError):
                delay = float(item["retryDelay"][:-1])
    if response.status_code in _SAFE_MESSAGE and error.get("message"):
        parts.append(str(error["message"])[:300])
    return _REDACT.sub("<redacted>", " | ".join(parts)), delay
