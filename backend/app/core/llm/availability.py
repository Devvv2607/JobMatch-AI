"""Startup check: does each provider still offer the model we are configured to use?

Groq shut down `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` on 2026-08-16; the
repo kept defaulting to one of them and every call returned 404. Now the API asks each
enabled provider's OpenAI-compatible `GET /models` at startup. A configured model that is
not listed is logged as an error and marked unavailable, and LLMClient routes around that
provider (the fallback chain continues, or the caller gets its degraded mode).

If the check itself fails (network, auth, timeout) nothing is marked: an outage of the
models endpoint must not disable a provider that may still answer.
"""

import logging
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.core.metrics import LLM_MODEL_AVAILABLE

logger = logging.getLogger(__name__)

# (provider name, model id) -> why it is unavailable
_unavailable: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class ProviderModels:
    name: str
    base_url: str
    api_key: str
    models: frozenset[str]


def is_unavailable(provider: str, model: str) -> bool:
    return (provider, model) in _unavailable


def reset() -> None:
    _unavailable.clear()


def configured(settings: Settings) -> list[ProviderModels]:
    """Every enabled provider with the models this deployment calls on it."""
    out = []
    if settings.groq_api_key:
        out.append(
            ProviderModels(
                "groq",
                settings.groq_base_url,
                settings.groq_api_key,
                frozenset({settings.groq_model, settings.groq_fast_model}),
            )
        )
    if settings.gemini_api_key:
        out.append(
            ProviderModels(
                "gemini",
                settings.gemini_base_url,
                settings.gemini_api_key,
                frozenset({settings.gemini_model}),
            )
        )
    if settings.ollama_enabled:
        out.append(
            ProviderModels(
                "ollama", settings.ollama_base_url, "", frozenset({settings.ollama_model})
            )
        )
    return out


def _model_ids(body: object) -> set[str]:
    data = body.get("data", []) if isinstance(body, dict) else []
    ids = set()
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.add(item["id"].removeprefix("models/"))  # Gemini lists "models/<id>"
    return ids


async def check_models(providers: list[ProviderModels], http: httpx.AsyncClient) -> None:
    for provider in providers:
        url = provider.base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
        try:
            response = await http.get(url, headers=headers)
            response.raise_for_status()
            offered = _model_ids(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "llm model check failed; provider left enabled",
                extra={"provider": provider.name, "error": type(exc).__name__},
            )
            continue
        if not offered:
            logger.warning(
                "llm model check: provider listed no models; left enabled",
                extra={"provider": provider.name},
            )
            continue
        for model in sorted(provider.models):
            key = (provider.name, model)
            if model in offered:
                _unavailable.pop(key, None)
                LLM_MODEL_AVAILABLE.labels(provider.name, model).set(1)
                logger.info(
                    "llm model available", extra={"provider": provider.name, "model": model}
                )
            else:
                _unavailable[key] = "not listed by the provider's /models endpoint"
                LLM_MODEL_AVAILABLE.labels(provider.name, model).set(0)
                logger.error(
                    "configured LLM model is not offered by the provider; "
                    "calls to it are disabled until the setting is fixed and the API restarts",
                    extra={
                        "provider": provider.name,
                        "model": model,
                        "offered": sorted(offered)[:50],
                    },
                )


async def check_configured_models(settings: Settings) -> None:
    async with httpx.AsyncClient(timeout=10) as http:
        await check_models(configured(settings), http)
