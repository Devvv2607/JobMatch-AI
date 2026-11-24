# JobMatch AI — Plan

Status: **awaiting go-ahead**. Nothing is built yet. This file covers the architecture, the schema, where I deviate from or tighten the brief, and the questions whose answers change the design.

## 1. What gets built

A career agent that reads a pool of 1,000+ live postings and gives a candidate at most five per day, each with a computed reason and its gaps; tailors the resume for the ones they pick with every claim traced back to the source resume; and runs a mock interview.

The three things a reviewer should be able to verify by re-running a script:

1. Retrieval quality — an ablation table (BM25 → vector → RRF → rerank → personalised) on a 500-pair labelled set.
2. Search latency — p50/p95 per stage, hardware recorded.
3. Verifier traceability — supported claims / total claims over 20+ resume×JD pairs, including adversarial ones.

## 2. Architecture

```
                 Next.js (App Router, TanStack Query, generated API types)
                                   │  /api/v1  (JSON + SSE)
                                   ▼
┌──────────────────────────── FastAPI (api) ─────────────────────────────┐
│ auth · rate limit · request-id/timing middleware · error envelope      │
│ routers: jobs search profile tailor agent interview tracker metrics    │
│                 │ thin: validate → call service → shape                │
│ services  ◄─────┴───── the same functions the agent tools call         │
│ retrieval/  filters → bm25 ∥ vector → rrf → rerank → personalise → explain
│ models in-process: bge-small (ONNX int8), MiniLM cross-encoder (ONNX int8), bm25s index
└───────┬───────────────────────┬───────────────────────┬────────────────┘
        │ SQL                   │ enqueue / status      │ LLM
        ▼                       ▼                       ▼
 Postgres 16 + pgvector     Redis ── arq worker     LLMClient
 (data, HNSW, checkpointer, (queue, rate limits,    Groq → Gemini → Ollama
  llm cache)                 quotas, index version)  (retry, fallback, cache, schema repair)
                                │
                                └ worker tasks: ingest, embed, parse resume, tailor,
                                  verify, score interview, daily digest (arq cron)

Observability: JSON logs (request id) · /metrics → Prometheus → Grafana · Langfuse (LLM traces) · Sentry (optional)
```

Rules that keep this honest:

- **One service layer.** REST routers and agent tools both call `app/<domain>/service.py`. No logic in routers or tools.
- **One user-scoping dependency.** `CurrentUser` + a `scoped(session, user)` helper; every user-owned query goes through it. Cross-user tests are written per table as the table is introduced, not at the end.
- **One LLM entry point.** `core/llm` is the only module that imports a provider SDK. Prompts are files under `app/prompts/<name>/v<N>.md`; the version is part of the cache key.
- **Untrusted text is data.** Job descriptions and resume text are HTML-sanitised on ingest, passed to the LLM inside delimited blocks in the user turn, never concatenated into system prompts, and every LLM output is parsed into a Pydantic schema before use.

### 2.1 Retrieval pipeline

```
query text and/or profile
  → hard filters (SQL): status, dealbreakers, work eligibility  → allowed job ids (+ ruled-out list with the rule)
  → BM25 top 100 (bm25s, masked to allowed ids)  ∥  vector top 100 (pgvector HNSW, same WHERE)
  → RRF (k=60)
  → cross-encoder rerank top 30
  → personalised re-score (weights in config)
  → top N + computed explanation      (LLM sentence fetched lazily from a separate endpoint)
```

- **What gets embedded:** one vector per job from a "job card" — title, seniority, skills, then the description truncated to the model's 512-token limit. One vector per job keeps dedup, the feedback centroid and the HNSW index simple. Chunking is a tuning experiment for after Phase 4, not a starting assumption.
- **Filtered vector search:** HNSW applies filters after the index scan, so a selective filter can return fewer than 100 rows. I will use pgvector's iterative index scan (0.8+) and record `EXPLAIN ANALYZE` for the filtered and unfiltered query in `docs/`.
- **Explanation object** is computed from structured fields (taxonomy skill sets, years of experience vs seniority, preference matches). The LLM sentence receives only that object, and its output is checked: any skill name it mentions that is not in the object causes the sentence to be dropped.
- **Ruled out** is produced by the filter stage itself: each dealbreaker is a typed rule that compiles to a SQL predicate, and the same rule is evaluated to label the excluded rows, so the list cannot disagree with the filter.

### 2.2 Resume engine and verifier

```
PDF → (worker) magic-byte + size check → text with char offsets → LLM extraction → CandidateProfile
       every item carries span = (start, end) into the stored resume text; spans are validated
       (the quoted text must literally occur at that offset) or the item is flagged for the user

tailor(JD) → keyword analysis → rewritten bullets + cover letter (schema-validated)
           → split into atomic claims
           → per claim: retrieve top source spans (embedding) → rule checks → LLM entailment judge
           → supported(span id) | unsupported | needs_review
           → unsupported: one regeneration attempt, then removed.  Never shown as accepted text.
```

Rule checks run before and override the LLM judge: every number, tool/skill name (via the taxonomy) and employer name in a claim must appear in the cited span. A claim the judge calls supported but that fails a rule check is `unsupported`. This is the "enforced by code" guarantee.

### 2.3 Agent

`router → {job_search, match_explain, resume_tailor, skill_gap, interview_prep, tracker, fallback}`. The router is one LLM call constrained to an enum + confidence; below threshold it asks a clarifying question; on any parse failure it routes to fallback. Multi-step requests are a short ordered list of routes from the same fixed set (max steps and a per-turn timeout in config). Write tools (`save_resume_version`, `set_tracker_status`, `remember`) pause on a LangGraph interrupt and resume only on an explicit confirm from the UI. Short-term memory is the Postgres checkpointer; long-term is `user_memory`.

## 3. Schema

All ids are UUIDs. `user_id` on every user-owned table, `ON DELETE CASCADE` from `users` so account deletion is one statement plus file and trace cleanup.

**Shared (no user_id)**

| Table | Key columns |
|---|---|
| `companies` | name, source, board_token, industry tags (from `companies.yaml`) |
| `jobs` | company_id, title, title_norm, location, remote_policy, eligible_regions[], eligibility_source, employment_type, seniority, salary_min/max/currency, salary_min_usd/max_usd, description, skills[], source, source_url, posted_at, first_seen_at, last_seen_at, missed_runs, content_hash, status (`live`/`updated`/`stale`/`expired`), duplicate_of, embedding vector(384), embedded_hash |
| `ingest_runs` | source, started/finished, fetched/new/updated/expired/failed counts, error |
| `llm_cache` | key = hash(prompt version, model, input), response, created_at |

Indexes on `jobs`: HNSW (cosine) on embedding; GIN on skills and eligible_regions; btree on status, posted_at, company_id, salary_min_usd; unique (source, source_id); btree on content_hash.

**User-owned**

| Table | Purpose |
|---|---|
| `users`, `refresh_tokens` | Argon2 hash; refresh tokens stored hashed, with a family id so reuse of a rotated token revokes the family |
| `resumes` | file path (outside web root), extracted text, parse status |
| `candidate_profiles` | validated `CandidateProfile` JSONB (items with spans), country, years of experience, preferences JSONB |
| `resume_spans` | resume_id, start, end, text, embedding — the verifier's retrieval corpus |
| `dealbreakers` | kind (enum), value JSONB, strict flag |
| `job_feedback` | job_id, action (`saved`/`dismissed`/`applied`) — feeds the centroid |
| `digests`, `digest_items` | daily short list and ruled-out list with the rule |
| `applications`, `application_notes`, `reminders` | tracker |
| `tailoring_runs`, `claims`, `resume_versions` | per application: generated changes, per-claim verdict + span id, accepted/rejected state, exported version |
| `user_memory` | kind (enum), content, source thread, created_at |
| `agent_threads` | ownership record for LangGraph checkpointer threads (checkpointer tables are created by its own setup) |
| `interview_sessions`, `interview_questions`, `interview_answers` | questions, transcript, four 1–5 scores with evidence quotes |
| `background_tasks` | arq job id, kind, status, result ref — what the UI polls |

Rate limits and the per-user daily LLM quota are Redis counters, not tables.

## 4. Where I tighten or deviate from the brief

These are deliberate. Say so if you disagree with any of them.

1. **BM25 "incremental" means incremental tokenising, not incremental indexing.** `bm25s` builds an immutable index. I will persist the tokenised corpus, tokenise only new/changed jobs, rebuild the index (well under a second at a few thousand documents), write it atomically to a volume, and bump a version key in Redis that the API watches to hot-swap. I will describe it that way in the README.
2. **Eval runs on a frozen corpus snapshot, not the live database.** Live jobs expire, so labels against the live DB rot and CI could not reproduce them. `eval/corpus/` holds the snapshot the 500 pairs were labelled on; `make eval` loads it into a scratch schema. The System page shows the last saved report.
3. **Two latency numbers, both reported.** The cross-encoder is CPU-bound, so p95 under concurrency is a different number from single-request p95. The benchmark script reports sequential p50/p95 per stage; the load test reports p50/p95 at stated concurrency. The 300 ms target is judged against whichever you choose in Q8; I will not pick the flattering one silently. Rerank inputs are truncated (title + skills + leading description) and the model is ONNX int8 to make the budget plausible.
4. **Recall@50 is over judged-relevant jobs only.** With 20 pooled candidates per query, unjudged jobs count as non-relevant. Standard for pooled evaluation, and stated next to the table.
5. **arq cron instead of APScheduler.** The worker already exists; a second scheduler is a second thing to run.
6. **One Postgres driver (psycopg 3)** for SQLAlchemy and the LangGraph checkpointer.
7. **Industry comes from `companies.yaml`.** Postings do not carry an industry, so "no fintech" can only be a hard filter if companies are tagged. Jobs from the remote-jobs API whose company is not in the file have unknown industry (see Q1).
8. **Static, dated FX table** in the repo for salary normalisation. Deterministic and offline; coarse is fine for a filter. Original amount and currency are kept.
9. **No nav entry until the screen exists.** Phase 1 ships login/register and an empty shell, not ten placeholder pages.
10. **The demo account is seeded from recorded outputs** (fictional resume, stored tailoring and interview results) so the two-minute walkthrough works with no API keys.
11. **Containers pin Python 3.12.** The host has 3.13; 3.12 has the safest wheel coverage for onnxruntime and tokenizers.

## 5. Phase 1 scope (what you review first)

- Repo layout from the brief, `git init`, pre-commit (ruff, mypy), Makefile.
- Compose: api, worker, db (pgvector/pg16), redis, frontend, prometheus, grafana; Langfuse per Q4.
- Config (pydantic-settings, complete `.env.example`), JSON logging with request ids, timing middleware, `/metrics`, `/healthz`, `/readyz`, error envelope, `/api/v1` prefix.
- Alembic baseline: `users`, `refresh_tokens`, `background_tasks`, `llm_cache`. Later tables arrive with their phase.
- Auth: register, login, refresh (rotation + reuse detection), logout; CSRF check on cookie endpoints; rate limiting.
- LLM client: provider interface, Groq/Gemini/Ollama adapters, timeout, backoff with jitter, fallback chain, schema validation with bounded repair, cache, token/latency logging. Tested against stubs only.
- Frontend: Next.js shell with the design tokens and fonts, login/register, generated API types.
- CI: ruff, mypy, pytest, frontend lint/typecheck/build, pip-audit, npm audit, Docker build.
- `docs/free-tier.md` with limits checked on the day for Groq and Gemini.

Checked at the start of the phase that uses them, from current docs: Greenhouse/Lever/Ashby/Remotive endpoint shapes and terms, `bm25s` masking API, pgvector iterative scan settings, Sentence Transformers ONNX export, LangGraph checkpointer and interrupt APIs, Langfuse self-host requirements and masking, Vapi web SDK and webhook payloads.

## 6. This machine

Ryzen 7 7445HS (12 threads), 15 GB RAM, Windows 11, Docker 29 + Compose v5, Node 22, Python 3.13, uv. **`make` is not installed.** The repo directory is empty and not yet a git repository. This is the hardware that will be recorded next to the latency numbers.

## 7. Open questions

**Change the design**

1. **Dealbreaker vs missing data.** Most postings list no salary; many "remote" postings do not say where from; some companies have no industry tag. When a dealbreaker cannot be evaluated, should the job be ruled out, or kept and flagged "salary not listed — check before applying"? My recommendation: a per-dealbreaker `strict` switch, defaulting to keep-and-flag, with work eligibility defaulting to strict. Ruling out on unknown salary would remove most of the pool.
2. **Which country is the primary candidate in?** Greenhouse/Lever/Ashby boards of AI-first companies skew heavily to US-only roles. If the demo candidate is in, say, India, the eligibility filter will legitimately remove most of the pool, and `companies.yaml` should be seeded toward companies that hire there or worldwide. I need the country to seed sensibly and to write realistic eval profiles.
3. **Label review.** 500 pairs at roughly 20–30 seconds each is three to four hours of your time. Will you review all of them, or a sample? I will report the `human` / `llm` / `llm-reviewed` split as it actually is either way, but it changes how the labelling tool prioritises (e.g. show judge-uncertain pairs first).
4. **Langfuse.** Current self-hosted Langfuse needs its own Postgres, ClickHouse, Redis and object storage — several GB of RAM on a 15 GB machine that is also running models. Recommendation: put it behind a Compose profile (`--profile tracing`), off by default, with LLM calls still logged as structured JSON. Acceptable, or must it be in the default `docker compose up`?
5. **Resumes for the parser gold set.** Do you have real resumes (yours or consented) to include, or should all 10+ be fictional ones I write in varied layouts? Fictional is safe to commit but easier than real-world PDFs, and the README would say so.

**Do not change the design, but I need them**

6. **`make`.** OK to rely on it (`winget install ezwinports.make`)? Every target will be a one-line `docker compose` command, so nothing is unusable without it.
7. **API keys.** Groq and Gemini free-tier keys are first needed for real in Phase 4 (LLM judge). Vapi key only in Phase 8.
8. **Which latency number is the 300 ms target** — single-request p95, or p95 under the load test? And what concurrency counts as realistic for you (I would propose 10 concurrent users)?
9. **GitHub.** Will you create the remote and push, or should I use `gh` after you confirm? CI cannot be shown green until one exists.

## Remaining phases

Order agreed 2026-11-24. One line each; a phase's brief file is its scope. Lines 6, 7 and
9 are the owner's (2026-11-24); lines 4, 5 and 8 are a reading of this plan until their
briefs arrive. Ideas borrowed from hireplz, by phase: [backlog-from-hireplz.md](docs/briefs/backlog-from-hireplz.md).

| Phase | Branch | Scope | Brief |
|---|---|---|---|
| 3b | `phase-3b-fixes` | Embedder batch consistency and re-embed, Redis persistence, Groq default model and startup check, explanation prompt wording, Phase 4 rerank candidates, automatic daily ingest with freshness metrics. | In the owner's message of 2026-11-24; summarised in the 3b PR. |
| 2b | `phase-2b-sources` | More job sources from official feeds only: YC (yc-oss) and VC-portfolio ATS boards, Himalayas, SmartRecruiters, Adzuna; cross-source dedup; `source_quality`; `startup_backed` dealbreaker. Before Phase 4. | [docs/briefs/phase-2b.md](docs/briefs/phase-2b.md) |
| 4 | | Evaluation: frozen corpus snapshot (including 2b sources), 500 labelled pairs, the ablation table, NDCG vs latency for the rerank candidates in ADR 0003. | not yet written |
| 5 | | Resume upload and parsing into a stored `CandidateProfile` with spans; search reads the stored profile and dealbreakers. Backlog: requirement blockers, skill adjacency, ghost-job signal, natural-language search intent, liveness probe. | not yet written; [backlog-from-hireplz.md](docs/briefs/backlog-from-hireplz.md) |
| 6 | | Tailoring + verifier: ATS keyword analysis, skill gaps, tailored bullets and cover letter (schema-validated), claim verifier with traceability %, per-change accept/reject diff UI, resume versions, verifier eval incl. adversarial JDs, plus the experience bank with provenance (see backlog). | not yet written; [backlog-from-hireplz.md](docs/briefs/backlog-from-hireplz.md) |
| 7 | | Career agent: LangGraph fixed-route router, tools over the shared service layer, confirm-before-write, short- and long-term memory with view/delete, streaming chat screen with visible steps, router eval, plus an MCP server (see backlog). | not yet written; [backlog-from-hireplz.md](docs/briefs/backlog-from-hireplz.md) |
| 8 | | Mock interview with voice (Vapi). | not yet written |
| 9 | | Tracker + Readiness + System: application tracker with notes, reminders and analytics; Readiness (skill gaps from live postings, readiness score, market signals); System page (eval table, latency, freshness, % verified live); saved searches with Telegram/email alerts (see backlog). | not yet written; [backlog-from-hireplz.md](docs/briefs/backlog-from-hireplz.md) |
| 10 | | Production Compose and zero-cost deploy. | [docs/briefs/phase-10.md](docs/briefs/phase-10.md) (placeholder until the brief arrives); [backlog-from-hireplz.md](docs/briefs/backlog-from-hireplz.md) |
