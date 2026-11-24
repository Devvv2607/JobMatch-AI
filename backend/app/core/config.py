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
    # Llama 3.x on Groq was shut down 2026-08-16 (deprecations page, checked 2026-11-24);
    # gpt-oss-120b is the production replacement Groq names.
    groq_model: str = "openai/gpt-oss-120b"
    # Small non-reasoning model for short outputs (the match sentence): reasoning models
    # spend max_tokens on reasoning (gpt-oss at 200 tokens: json_validate_failed).
    # Checked 2026-11-24 against this account's /models (no Llama models are listed):
    # 15/15 valid sentences at max_tokens 200, p50 206 ms, <= 49 completion tokens.
    groq_fast_model: str = "qwen/qwen3.8-27b"
    groq_fast_reasoning_effort: str = "none"
    # reasoning_effort sent with GROQ_MODEL calls; empty = not sent.
    groq_reasoning_effort: str = ""
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

    # Embedding model, baked into the image by backend/Dockerfile.
    embedding_model_dir: str = "/opt/models/bge-small-en-v1.5"
    embedding_model_file: str = "model_quint8_avx2.onnx"
    embedding_threads: int = Field(default=0, ge=0)  # 0 = onnxruntime decides

    # Ingestion.
    ingest_cron_enabled: bool = False
    ingest_cron_hours: str = "3,15"  # UTC hours for the scheduled run, comma-separated
    ingest_concurrency: int = Field(default=4, ge=1, le=16)
    ingest_http_timeout_seconds: float = 30.0
    ingest_stale_after_days: int = 45
    ingest_expire_after_missed_runs: int = 2
    # Hiding near-duplicates (embedding cosine above the threshold) is off: on the
    # 2026-11-20 pool it merged distinct roles. Exact dedup always runs.
    ingest_near_duplicates_enabled: bool = False
    ingest_near_duplicate_threshold: float = Field(default=0.95, gt=0, lt=1)
    # Boilerplate stripping for the embedding and search text: a paragraph is dropped
    # when it appears in at least this share of one company's distinct descriptions,
    # for companies with at least this many distinct descriptions.
    ingest_boilerplate_min_share: float = Field(default=0.3, gt=0, le=1)
    ingest_boilerplate_min_postings: int = Field(default=5, ge=2)
    remotive_min_interval_hours: float = 6.0  # Remotive asks for at most 4 fetches a day

    # Retrieval (Phase 3). Defaults only: nothing here is tuned until the Phase 4 eval.
    reranker_model_dir: str = "/opt/models/ms-marco-MiniLM-L6-v2"
    reranker_model_file: str = "model.onnx"  # fp32: int8 scores were batch-dependent
    reranker_threads: int = Field(default=0, ge=0)  # 0 = onnxruntime decides
    reranker_batch_size: int = Field(default=8, ge=1, le=64)
    # Two rerank profiles (ADR 0003). Top = fused candidates the cross-encoder scores;
    # tokens = per (query, job) pair: the query, then title, skills and the start of
    # search_text (the model's own limit is 512).
    # interactive: POST /search. Interim default; the final value is chosen in Phase 4
    # from the NDCG-vs-latency table (no rerank, 10@128, 20@128, 30@256).
    rerank_interactive_top: int = Field(default=10, ge=0, le=100)
    rerank_interactive_tokens: int = Field(default=128, ge=32, le=512)
    # digest: the offline "Today" list, where latency matters less.
    rerank_digest_top: int = Field(default=30, ge=0, le=100)
    rerank_digest_tokens: int = Field(default=256, ge=32, le=512)
    bm25_index_dir: str = "/data/bm25"
    # How often the API checks Redis for a newer BM25 index (hot swap).
    bm25_version_check_seconds: float = Field(default=2.0, ge=0)
    search_candidates: int = Field(default=100, ge=10, le=500)  # per retriever
    search_rrf_k: int = Field(default=60, ge=1)
    search_hnsw_ef_search: int = Field(default=100, ge=10, le=1000)
    search_ruled_out_limit: int = Field(default=20, ge=0, le=100)
    search_page_size: int = Field(default=10, ge=1, le=30)
    search_cache_seconds: int = Field(default=300, ge=0)
    rate_limit_search_per_minute: int = 60
    # Personalised re-score: final = weighted mean of the components that are available
    # for the request (a query without a profile has only the reranker).
    search_weight_rerank: float = Field(default=0.6, ge=0)
    search_weight_skills: float = Field(default=0.25, ge=0)
    search_weight_experience: float = Field(default=0.1, ge=0)
    search_weight_preferences: float = Field(default=0.05, ge=0)
    # LLM explanation sentences per user per UTC day.
    llm_daily_quota_per_user: int = Field(default=50, ge=0)

    @property
    def ingest_cron_hour_set(self) -> set[int]:
        return {int(h) for h in self.ingest_cron_hours.split(",") if h.strip()}

    @property
    def near_duplicate_threshold(self) -> float | None:
        """The near-duplicate cosine threshold, or None when the pass is off."""
        if not self.ingest_near_duplicates_enabled:
            return None
        return self.ingest_near_duplicate_threshold

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
