# Decision log

Small decisions, one line each, newest last. Larger ones get their own ADR in this folder.

| Date | Phase | Decision |
|---|---|---|
| 2026-11-17 | 1 | Containers pin Python 3.12 (wheel coverage for onnxruntime/tokenizers); the host's 3.13 is not used. |
| 2026-11-17 | 1 | One psycopg 3 driver for SQLAlchemy async, Alembic and later the LangGraph checkpointer. |
| 2026-11-17 | 1 | Migrations run in a one-shot `migrate` Compose service; api and worker start only after it exits 0. |
| 2026-11-17 | 1 | Refresh tokens: 48 random bytes, stored as SHA-256 (no salt needed for random tokens), one family per login; reuse of a rotated token revokes the family. |
| 2026-11-17 | 1 | Refresh cookie is scoped to `Path=/api/v1/auth`, so it is never sent to any other endpoint. |
| 2026-11-17 | 1 | CSRF on cookie endpoints: required `X-Requested-With: jobmatch` header plus an Origin allow-list check. No CSRF token needed because the cookie is only read by refresh/logout. |
| 2026-11-17 | 1 | Logout revokes the whole token family of that login, not other logins of the same user. |
| 2026-11-17 | 1 | Frontend serialises refreshes (shared promise in a tab, Web Locks across tabs) so two tabs or React's double effect cannot trip reuse detection. |
| 2026-11-17 | 1 | Access token lives in memory only, never in localStorage. |
| 2026-11-17 | 1 | Rate limiter is a Redis fixed window and fails open if Redis is down (logged), so a cache outage cannot lock everyone out. |
| 2026-11-17 | 1 | Another user's row is reported as 404, never 403, so ids cannot be probed. |
| 2026-11-17 | 1 | A test fails if any mapped table is neither in `SHARED_TABLES` nor `UserOwned` with a cascading, non-null `user_id`. |
| 2026-11-17 | 1 | One OpenAI-compatible HTTP adapter covers Groq, Gemini and Ollama; no provider SDKs. |
| 2026-11-17 | 1 | LLM cache is a Postgres table keyed on sha256(prompt name, prompt version, model, messages, max_tokens); only temperature-0 calls are cached; stored rows hold output only. |
| 2026-11-17 | 1 | Backoff: full jitter, base 0.5 s, cap 8 s; `retry-after` honoured up to the cap. |
| 2026-11-17 | 1 | Validation errors never echo the rejected input (it may be a password). |
| 2026-11-17 | 1 | HTTP metrics are labelled by route template (`/tasks/{task_id}`), not raw path, to bound cardinality. |
| 2026-11-17 | 1 | Next.js `output: "standalone"`, served by `node server.js` as the non-root `node` user. |
| 2026-11-17 | 1 | TypeScript pinned to 5.9: `openapi-typescript` 7.13 requires `typescript ^5`. |
| 2026-11-17 | 1 | TanStack Query not installed yet: nothing fetches data in Phase 1. It arrives with the first data screen. |
| 2026-11-17 | 1 | Signed-in landing page (`/`) shows only the account email and sign-out: needed to demonstrate the session, and not a placeholder for later screens. |
| 2026-11-17 | 1 | Langfuse and Sentry deferred: Langfuse lands with the first real LLM feature (behind `--profile tracing`), Sentry in Phase 10. |
| 2026-11-17 | 1 | Per-user daily LLM quota lands with the first LLM-backed endpoint (Phase 3 explanations). |
| 2026-11-17 | 1 | LLM calls are routed by data class; personal data never reaches Gemini. See [ADR 0001](0001-llm-data-routing.md). |
| 2026-11-17 | 1 | Rate-limit dependencies read their limit from settings on each request, not at import. |
| 2026-11-17 | 1 | Login and register share one per-IP bucket (10/min) plus a per-email failure lockout (5 per 15 min, window starts at the first failure, successes not counted, not reset by success). |
| 2026-11-17 | 1 | A duplicate registration (409) counts as a failure for that email, like a wrong password. |
| 2026-11-17 | 1 | Every 429 uses the same message, so it never reveals which limit applied or whether an email exists. Failure counters key on sha256(email), not the address. |
| 2026-11-17 | 1 | Refresh is limited per token family (30/min), checked after the token is validated and before rotation, so a limited refresh does not consume the cookie. |
| 2026-11-17 | 1 | Client IP is the socket peer unless TRUSTED_PROXY_COUNT=N > 0, then the Nth X-Forwarded-For entry from the right; uvicorn runs with --no-proxy-headers. |
| 2026-11-17 | 2 | Failed refreshes are limited per IP (20 per 10 min). Only a presented token that fails counts; a request with no cookie (signed-out page load) does not. |
| 2026-11-17 | 2 | Production topology: API same-site behind a Next.js rewrite, cookie stays SameSite=Lax. See [ADR 0002](0002-same-site-api-via-nextjs-rewrite.md), including the client-IP caveat. |
| 2026-11-17 | 1 | Memory budget: the default Compose stack must stay within the 6 GB WSL2 cap under load. |
