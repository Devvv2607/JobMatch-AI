from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-secret-not-for-production-use-0000000000"  # noqa: S105


class Settings(BaseSettings):
    """All configuration comes from the environment (twelve-factor)."""

    model_config = SettingsConfigDict(extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://jobmatch:jobmatch@db:5432/jobmatch"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    redis_url: str = "redis://redis:6379/0"

    jwt_secret: str = DEV_JWT_SECRET
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 14 * 24 * 3600
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cors_origins: str = "http://localhost:3000"

    # Login and register: per client IP, every request counts.
    rate_limit_credentials_ip_per_minute: int = 10
    # Login and register: failed attempts per normalised email, in a window that starts
    # at the first failure. Successful logins do not count.
    login_failure_limit: int = 5
    login_failure_window_seconds: int = 900
    # Refresh: per refresh-token family (one login), not per IP, because every page
    # load refreshes and many users can share one IP.
    rate_limit_refresh_per_family_per_minute: int = 30
    # Refresh: failed attempts (a presented token that is invalid, expired, revoked or
    # reused) per client IP. Successful refreshes do not count.
    refresh_failure_limit: int = 20
    refresh_failure_window_seconds: int = 600
    rate_limit_default_per_minute: int = 120
    # Number of reverse proxies in front of the API that append to X-Forwarded-For.
    # 0 means the header is ignored and the socket address is the client IP.
    trusted_proxy_count: int = Field(default=0, ge=0, le=5)

    llm_provider_order: str = "groq,gemini,ollama"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    ollama_enabled: bool = False
    ollama_model: str = "llama3.2"
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = Field(default=3, ge=0, le=6)
    llm_repair_attempts: int = Field(default=2, ge=0, le=4)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _refuse_dev_secret_in_production(self) -> "Settings":
        if self.environment == "production":
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be set to a 32+ character secret in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
