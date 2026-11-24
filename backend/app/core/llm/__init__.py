import httpx

from app.core.config import Settings
from app.core.db import SessionLocal
from app.core.llm.cache import PostgresLLMCache
from app.core.llm.client import LLMClient
from app.core.llm.providers import OpenAICompatProvider
from app.core.llm.types import LLMProvider


def build_providers(settings: Settings, http: httpx.AsyncClient) -> list[LLMProvider]:
    """The fallback chain, in LLM_PROVIDER_ORDER. Providers without credentials are skipped."""
    configured = {
        "groq": (
            settings.groq_api_key != "",
            settings.groq_model,
            settings.groq_base_url,
            settings.groq_api_key,
            settings.groq_reasoning_effort,
        ),
        "gemini": (
            settings.gemini_api_key != "",
            settings.gemini_model,
            settings.gemini_base_url,
            settings.gemini_api_key,
            "",
        ),
        "ollama": (
            settings.ollama_enabled,
            settings.ollama_model,
            settings.ollama_base_url,
            "",
            "",
        ),
    }
    providers: list[LLMProvider] = []
    for name in (n.strip() for n in settings.llm_provider_order.split(",")):
        if name not in configured:
            raise ValueError(f"Unknown LLM provider in LLM_PROVIDER_ORDER: {name!r}")
        enabled, model, base_url, api_key, reasoning_effort = configured[name]
        if enabled:
            providers.append(
                OpenAICompatProvider(
                    name=name,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    http=http,
                    timeout_seconds=settings.llm_timeout_seconds,
                    reasoning_effort=reasoning_effort,
                )
            )
    return providers


def build_llm_client(settings: Settings, http: httpx.AsyncClient) -> LLMClient:
    return LLMClient(
        build_providers(settings, http),
        PostgresLLMCache(SessionLocal),
        max_retries=settings.llm_max_retries,
        repair_attempts=settings.llm_repair_attempts,
    )
