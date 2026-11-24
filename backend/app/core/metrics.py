from prometheus_client import Counter, Gauge, Histogram

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

SEARCH_STAGE_DURATION = Histogram(
    "search_stage_duration_seconds",
    "Time spent in each search stage",
    ["stage"],
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5),
)
SEARCHES = Counter("searches_total", "Search requests", ["outcome"])  # ok / cached / degraded
BM25_DOCUMENTS = Gauge(
    "bm25_index_documents",
    "Documents in the BM25 index the API serves",
    multiprocess_mode="max",
)
EXPLANATION_SENTENCES = Counter(
    "match_explanation_sentences_total", "LLM match sentences", ["outcome"]
)  # ok / dropped / unavailable

LLM_MODEL_AVAILABLE = Gauge(
    "llm_model_available",
    "1 if the provider's /models endpoint listed the configured model at startup, else 0",
    ["provider", "model"],
    multiprocess_mode="min",
)
