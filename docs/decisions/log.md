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
| 2026-11-17 | 2 | Embeddings: Sentence Transformers exports and quantises bge-small in a Docker build stage only; at runtime onnxruntime + tokenizers run the int8 file (CLS pooling + L2, as the model's own config says). No PyTorch in the API or worker. A build-time parity check fails the build if any check sentence's cosine to the fp32 reference drops below 0.98. |
| 2026-11-17 | 2 | Quantisation preset `avx2` (not `avx512_vnni`): portable to any x86-64 host with AVX2, which free container hosts may not exceed. It produces unsigned 8-bit weights, `model_quint8_avx2.onnx`. |
| 2026-11-17 | 2 | sentence-transformers 6.x cannot install its own `[onnx]` extra (it needs transformers>=5, optimum-onnx 0.1.0 needs <4.58). The build stage pins the resolver's working set: sentence-transformers 5.7.0, transformers 4.57.6 (backend/model/requirements.txt). |
| 2026-11-17 | 2 | Model revision pinned (BAAI/bge-small-en-v1.5 @ 5c38ec7c), so every build embeds identically. |
| 2026-11-17 | 2 | One embedding per job, from a "job card": title, level, skills, then description; the tokenizer truncates at 512 tokens. |
| 2026-11-17 | 2 | Eligibility order: on-site/hybrid → structured ATS country first; remote → the ATS location field first (a remote role's structured country is often just HQ), then the structured country, then description rules, else unknown. |
| 2026-11-17 | 2 | Greenhouse office records are only a fallback for eligibility, labelled `greenhouse.offices`, because remote roles are often attached to the head office. |
| 2026-11-17 | 2 | A location with no remote/hybrid marker and no source workplace field is `unknown`, not `onsite`, so a "no on-site" dealbreaker keeps and flags it instead of guessing. |
| 2026-11-17 | 2 | Seniority with no marker in the title ("Software Engineer") is `mid`. "Product/Program/Account Manager" are not people managers. |
| 2026-11-17 | 2 | Employment type defaults to full_time when neither the source nor the title says otherwise. |
| 2026-11-17 | 2 | Salary: structured source fields first, then the source's salary text, then the description; text is parsed only when it is a range with a currency. Single figures, "70K-80K" (no currency) and Indian digit grouping are left empty, not guessed. |
| 2026-11-17 | 2 | The content hash covers title, description, location and salary, so the same text in two cities is never an exact duplicate. |
| 2026-11-17 | 2 | Near-duplicates also need the same normalised location, work countries, scope and remote policy: they catch reworded reposts, never a role offered in two cities. |
| 2026-11-17 | 2 | Dedup is recomputed from scratch every run (and chains flattened), so it heals when an original expires. Ties go to the earlier first_seen, then posted_at, then id. |
| 2026-11-17 | 2 | A failed board fetch never counts as a miss: only boards fetched successfully can expire jobs. |
| 2026-11-17 | 2 | "updated" lasts one run; an unchanged job seen again goes back to live. "stale" ends only when the content changes. |
| 2026-11-17 | 2 | Remotive companies not in companies.yaml are created with unknown industry (empty tags). Company names join across sources by slug, so a Remotive posting from a configured company attaches to it. |
| 2026-11-17 | 2 | Remotive is fetched at most once per 6 h (REMOTIVE_MIN_INTERVAL_HOURS), inside its "max 4 a day" rule. |
| 2026-11-17 | 2 | In locations.yaml, "IN" is never read as Indiana, and Norway's code is quoted (YAML reads bare NO as false). |
| 2026-11-17 | 1 | Memory budget: the default Compose stack must stay within the 6 GB WSL2 cap under load. |
| 2026-11-18 | 2 | Ingest run status covers every stage for a source's jobs: rows are committed as `running` first and finished only after embed and dedup, as succeeded / partial / failed (or `skipped` for the Remotive interval), with `embedded`, `embed_pending` and `error`. Fixes runs reporting success before embedding. |
| 2026-11-18 | 2 | A store failure fails only that source; the other sources and the shared stages still run. |
| 2026-11-18 | 2 | A row still `running` 6 hours after it started is marked failed (interrupted) by the next run. |
| 2026-11-18 | 2 | The four rows of the interrupted first run (2026-11-17) were corrected by hand from succeeded to partial, with the reason in `error`; their jobs were stored but never embedded. |
| 2026-11-18 | 2 | `make ingest-embed` embeds pending jobs only (no fetching) and then dedups; it resumes an interrupted run and is not recorded as a source run. |
| 2026-11-18 | 2 | Remotive's public feed is small by design: 17 jobs in total on 2026-11-17 (its own `total-job-count`); one category alone returned 16. Not a filter or bug on our side. |
| 2026-11-21 | 2 | Near-duplicate hiding is off (`INGEST_NEAR_DUPLICATES_ENABLED=false`, the default); dedup recomputes from scratch, so rerunning it cleared the 2,470 near-duplicate marks. Exact dedup (content hash; company + title + location) is unchanged. |
| 2026-11-21 | 2 | **Deferred:** near-duplicates return only as "same company + same normalised title + cosine above a threshold tuned on a hand-labelled sample", shown as "also posted in X" and never hidden. Not built. |
| 2026-11-21 | 2 | Boilerplate stripping: a paragraph is a blank-line-separated block (how html_to_text renders blocks and list items), compared after `normalise_key`. It is dropped when it occurs in ≥30% of the company's *distinct* descriptions, for companies with ≥5 distinct descriptions. Counting distinct descriptions stops one role posted in many cities from looking like boilerplate. |
| 2026-11-21 | 2 | Boilerplate is judged against the company's current non-expired postings, so it can shift as the pool changes; only jobs whose stripped text actually changes are re-embedded. |
| 2026-11-21 | 2 | Embedding text v2 (`EMBED_TEXT_VERSION = 2`): title, level, skills, location, then the stripped description; the tokenizer truncates at 512. The version is part of `embed_input_hash`; `embedded_hash` now records the input hash a vector came from, so a version bump re-embeds every job. |
| 2026-11-21 | 2 | The stripped description is stored as `jobs.search_text`: Phase 3's BM25 and reranker read the same text the vectors were built from. The original description is kept unchanged. |
| 2026-11-21 | 2 | Store step loads only (source_id, id, content_hash, status) for existing jobs and writes with bulk statements. Rule-derived fields (eligibility, skills, seniority, salary parsing) are rewritten on unchanged postings too, so a rule change reaches every job on the next run. |
| 2026-11-21 | 2 | Locations: placeholders ("N/A", "LOCATION", "No Location", "In-person", bare "Remote") stay unknown; "CIS" stays unknown (no agreed country list). A "CC-Place" prefix ("IN-Bengaluru") is only read as country code + place when the whole token is not already a known place ("Cluj-Napoca"). |
| 2026-11-21 | 2 | The embedding model runs on one dedicated thread, not `asyncio.to_thread`. Measured: 40 batches on one thread peaked at 405 MiB RSS; spread over a warm 9-thread default pool (as in a real run, after httpx DNS lookups), 693 MiB, because each thread gets its own glibc malloc arena. |
| 2026-11-21 | 2 | Correction to the 2026-11-20 report: of that run's 1,146 MiB ingest-container peak, the store step accounted for ~809 MiB; the rest came during the embed stage. After the fixes the store step stays at 441–466 MiB (container) and a full run peaked at 834 MiB process RSS. |
| 2026-11-21 | 3 | Until resume parsing and stored profiles exist (Phase 5), the profile (skills, years, preferences) and the dealbreakers are sent with each search request. The rule and profile schemas are the ones that will be stored. |
| 2026-11-21 | 3 | A dealbreaker the posting cannot be checked against (salary not listed, workplace or eligibility unknown, company industry unknown) keeps the job and flags it, unless the rule is `strict`. A clear violation always rules the job out. |
| 2026-11-21 | 3 | `min_salary_usd` compares the top of the posted range (or the minimum when only that is given): a range that reaches the floor passes. |
| 2026-11-21 | 3 | "Ruled out" = the same query retrieved without the dealbreakers (BM25 and vector, RRF), minus what the filter allowed, best first, at most 20, each with every rule that excluded it. Labels come from the same per-rule SQL expression the filter uses. |
| 2026-11-21 | 3 | Vector search uses `hnsw.iterative_scan = relaxed_order` (pgvector 0.8.7) with `ef_search` 100, and re-sorts by distance in Python. |
| 2026-11-21 | 3 | The reranker scores each (query, job) pair separately. Batched int8 scores depended on the rest of the batch (dynamic quantisation scales over the whole tensor): up to 0.49 logit apart, 12 of 50 top-10 positions changed. Separate pairs were also faster (1.38 s vs 1.60 s for 30 pairs at 256 tokens). |
| 2026-11-21 | 3 | Re-score: the weighted mean of the components available for that job (rerank sigmoid 0.6, skill coverage 0.25, experience fit 0.1, preferences 0.05). A missing component (no profile skills, posting lists no skills, no years given) is left out of the mean, not counted as 0. Untuned until the Phase 4 eval. |
| 2026-11-21 | 3 | Experience fit uses a fixed years band per level (e.g. senior 5–10) and loses 0.25 per year outside it. Seniority comes from the title; a title without a level is "mid". |
| 2026-11-21 | 3 | With no query, the search text is the profile's canonical skills, space-separated. |
| 2026-11-21 | 3 | The API loads the embedder and reranker on the first search, not at startup; both run on one dedicated thread per API process. |
| 2026-11-21 | 3 | BM25 is rebuilt in full after every ingest and `make ingest-embed` (11,531 jobs: 9.2 s including the database read), written to the shared `bm25data` volume, published in Redis; the API checks the version every 2 s and swaps. The two newest versions are kept. |
| 2026-11-21 | 3 | Search responses are cached per user for 300 s; the key includes the BM25 version, so an ingest invalidates them. A cached response carries the timings of the search that produced it, and `cached: true`. |
| 2026-11-21 | 3 | The match sentence is an LLM call of data class "personal" (it sees the candidate's skills). It is generated from the computed explanation only; if it names a taxonomy skill not in that object it is withheld (`status: dropped`). The explanation is recomputed on the server; a client-sent explanation is never used. |
| 2026-11-21 | 3 | The daily LLM quota (50 per user, UTC day) counts every explanation request that reaches the LLM step, LLM-cache hits included, so the count does not depend on cache state. |
| 2026-11-21 | 3 | Match sentence `max_tokens` is 1024, not 200: gpt-oss on Groq counts reasoning tokens against the limit, and at 200 the JSON was cut off (Groq `json_validate_failed`; the call used 333 tokens). |
| 2026-11-21 | 3 | After the disk-full crash corrupted cached image layers, the backend image was rebuilt without cache. The uv cache mount now has its own id (`jobmatch-uv`), and the model stage installs without a pip cache mount (saves ~1 GB; it rarely rebuilds). |
