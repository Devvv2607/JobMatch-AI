from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0, 10.0),
)

LLM_CALLS = Counter("llm_calls_total", "LLM provider calls", ["provider", "model", "outcome"])
LLM_DURATION = Histogram(
    "llm_call_duration_seconds",
    "LLM provider call duration",
    ["provider", "model"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0, 60.0),
)
LLM_TOKENS = Counter("llm_tokens_total", "LLM tokens used", ["provider", "model", "kind"])
LLM_CACHE_HITS = Counter("llm_cache_hits_total", "LLM responses served from cache")
