# JobMatch AI

A career agent that reads a large pool of job postings and gives a candidate the few that
fit, each with the reason and the gaps. It then tailors the resume for the roles they
choose, with every claim traced back to the original resume, and preps them for the
interview.

**Status: Phase 2 of 10 (ingestion).** Accounts, sessions, the LLM client, observability,
CI and the job pool exist: live postings from 82 company boards and Remotive, normalised,
deduplicated, tagged with work eligibility and embedded. Search, matching and every product
screen are still to come; see [PLAN.md](PLAN.md). Retrieval quality and latency are not
reported yet, because they have not been measured.

## Run it locally

Needs Docker Desktop (or Docker Engine with Compose v2) and ~1 GB of free memory.

```sh
docker compose up -d --build
```

No `.env` is needed for local use: every setting has a development default in
`docker-compose.yml`. Copy `.env.example` to `.env` only to change something, such as
adding LLM keys.

| Service | URL |
|---|---|
| App | <http://localhost:3000> |
| API docs (OpenAPI) | <http://localhost:8000/docs> |
| Prometheus | <http://localhost:9090> |
| Grafana (admin / admin) | <http://localhost:3001>, dashboard "JobMatch API" |

Create an account at <http://localhost:3000/register>.

## Commands

Each `make` target is a single command; the command itself is listed so `make` is optional.

| make | Command |
|---|---|
| `make up` | `docker compose up -d --build` |
| `make down` | `docker compose down` |
| `make reset` | `docker compose down -v` (deletes all data) |
| `make ps` | `docker compose ps -a` |
| `make logs` | `docker compose logs -f api worker` |
| `make test` | `docker compose run --rm api pytest --cov=app --cov-report=term-missing` |
| `make lint` | `docker compose run --rm --no-deps api sh -c "ruff check . && ruff format --check ."` |
| `make typecheck` | `docker compose run --rm --no-deps api mypy app tests scripts` |
| `make migrate` | `docker compose run --rm migrate` |
| `make openapi` | `docker compose run --rm --no-deps -T api python -m scripts.export_openapi > frontend/openapi.json && npm --prefix frontend run gen:api` |
| `make fe-check` | `npm --prefix frontend run lint && npm --prefix frontend run typecheck && npm --prefix frontend run build` |
| `make ingest` | `docker compose run --rm ingest python -m app.ingest.cli run` |
| `make ingest-embed` | `docker compose run --rm ingest python -m app.ingest.cli embed` |
| `make ingest-report` | `docker compose run --rm --no-deps ingest python -m app.ingest.cli report --country IN` |
| `make check-boards` | `docker compose run --rm --no-deps ingest python -m app.ingest.cli check-boards` |
| `make bm25` | `docker compose run --rm ingest python -m app.ingest.cli bm25` |
| `make bench-search` | `docker compose run --rm -e EMBEDDING_THREADS=4 -v ./docs/bench:/out ingest python -m scripts.bench_search --out /out` |
| `make backup` | `sh ops/backup.sh backup` (pg_dump custom format into `backups/`, gitignored) |
| `make backup-check` | `sh ops/backup.sh check` (restore the newest backup into a scratch database and compare row counts) |

Tests run against a separate `jobmatch_test` database and Redis db 15, so they never
touch your development data. No test calls a real LLM or the network.

Pre-commit hooks (ruff, mypy, whitespace, private-key and `.env` guards):
`uvx pre-commit install`.

## Windows notes

- The repo works from a path containing spaces (it is developed in one).
- `.gitattributes` forces LF line endings, because all code runs in Linux containers.
- `make` is not built in: `winget install ezwinports.make`, or run the commands above.
- **Cap WSL2 memory** so Docker cannot starve Windows. The project's budget assumes a
  6 GB cap. In `%UserProfile%\.wslconfig`:

  ```ini
  [wsl2]
  memory=6GB
  processors=4
  swap=2GB
  ```

  Then run `wsl --shutdown` and restart Docker Desktop.

## Memory footprint

**Budget:** the default `docker compose up` stack must fit in 6 GB (the WSL2 cap above)
**under load**, not only at idle.

Measured with `docker stats --no-stream` on 2026-11-17, at idle, right after
`docker compose up` from empty volumes, on an AMD Ryzen 7 7445HS (6 cores / 12 threads),
15 GB RAM, Windows 11, Docker 29.4 with WSL2 capped at 6 GB:

| Service | Resident |
|---|---|
| grafana | 251 MiB |
| api | 81 MiB |
| prometheus | 76 MiB |
| worker | 71 MiB |
| db | 40 MiB |
| frontend | 37 MiB |
| redis | 6 MiB |
| **Total** | **562 MiB** |

This is an idle number with no ML models loaded, so it says little about the budget yet.
The embedding and reranking models arrive in Phases 2 and 3; from then on this table is
re-measured under the load test against the 6 GB budget.

## Architecture (Phase 1)

```
Next.js (login/register) ──/api/v1──▶ FastAPI ──▶ Postgres 16 + pgvector
                                        │  ├────▶ Redis (rate limits, arq queue)
                                        │  └────▶ LLM client (routed by data class)
                                        └ /metrics ◀── Prometheus ◀── Grafana
                          arq worker ──▶ Postgres, Redis (scheduled jobs)
```

- **Auth:** Argon2id passwords; 15-minute JWT access token held in memory by the browser;
  rotating refresh token in an httpOnly cookie scoped to `/api/v1/auth`. Reusing a
  rotated refresh token revokes every token from that login.
- **User isolation:** every user-owned table has a cascading `user_id`, and reads go
  through one scoping helper. Tests prove one user cannot read another's rows, and a test
  fails if a new table skips scoping.
- **LLM data routing:** every call declares `personal` or `public`. Personal data (resume,
  profile, interview answers, agent turns) goes only to Groq, then local Ollama, never
  Gemini; public data (job postings, fictional eval data) may also use Gemini. Enforced in
  code and tested; see [ADR 0001](docs/decisions/0001-llm-data-routing.md).
- **LLM client:** one entry point with retry (exponential backoff, full jitter,
  `retry-after`), a provider fallback chain, schema validation with bounded repair,
  a Postgres response cache, and token/latency logging. Prompts live in versioned files.
  Prompt and resume text is never logged.
- **Observability:** JSON logs with a request id on every line and response; Prometheus
  metrics by route template; a provisioned Grafana dashboard.

Small decisions are logged in [docs/decisions/log.md](docs/decisions/log.md). LLM
free-tier limits, with the date checked, are in [docs/free-tier.md](docs/free-tier.md).

## Job ingestion

`make ingest` runs one ingestion. A scheduled run in the worker exists but is off by
default (`INGEST_CRON_ENABLED`).

```
companies.yaml (82 boards) ─┐
                            ├─▶ adapters ─▶ normalise ─▶ upsert ─▶ misses/expiry ─▶ stale
Remotive (max 4×/day) ──────┘   Greenhouse  html→text      (source,   (only boards     (45 d
                                Lever       eligibility     source_id) fetched OK)      unchanged)
                                Ashby       skills, level                                  │
                                Remotive    salary→USD                                     ▼
                                     exact dedup ◀── embed ◀── strip company boilerplate
                                                  (changed cards only)
```

- **Sources:** Greenhouse, Lever and Ashby public job-board APIs for the companies in
  [`companies.yaml`](backend/app/ingest/data/companies.yaml), which were chosen because
  they currently hire in India, APAC or worldwide-remote, plus the Remotive feed.
  `make check-boards` re-checks every token.
- **Work eligibility** is three-state for a candidate's country: eligible, ineligible or
  unknown. It comes from structured ATS fields first (Lever `country`, Ashby postal
  addresses), then location fields, then description rules. No LLM is involved. Each job
  stores which rule decided (`eligibility_source`), and `make ingest-report` counts them.
- **Skills** map to a canonical taxonomy with aliases
  ([`skills.yaml`](backend/app/ingest/data/skills.yaml)); "Postgres" and "PostgreSQL" are one skill.
- **Salaries** keep the original amount, currency and interval, plus annual USD from a dated
  ECB rate table ([`fx_rates.yaml`](backend/app/ingest/data/fx_rates.yaml)).
- **Dedup:** exact duplicates only, found by content hash or by company + title +
  location; they point to their original (`duplicate_of`). Near-duplicate hiding by
  embedding similarity is off (`INGEST_NEAR_DUPLICATES_ENABLED=false`): it merged distinct
  roles. Its replacement, "also posted in X" (never hidden), is deferred.
- **Freshness:** jobs are live, updated, stale (unchanged for 45+ days) or expired (missing
  from 2 consecutive successful fetches).
- **Boilerplate stripping:** paragraphs that recur in 30% or more of a company's distinct
  descriptions (about-us, benefits, equal-opportunity text, section headings) are removed,
  for companies with 5 or more. The result is stored as `search_text`, the text that is
  embedded and, from Phase 3, searched. No LLM involved.
- **Embeddings:** `bge-small-en-v1.5`, exported to fp32 ONNX at image build time and
  run with onnxruntime, with no PyTorch at runtime (int8 was dropped: its vectors
  depended on the other jobs in the batch). The input is a "job card": title, level,
  skills, location, then `search_text`, truncated at 512 tokens. The recipe
  (`EMBED_TEXT_VERSION`) and the model (`MODEL_VARIANT`) are part of each job's input
  hash; only jobs whose hash changed are re-embedded, so a recipe or model change
  re-embeds all of them.
- **Remotive attribution:** Remotive's terms require naming Remotive and linking to the
  job's Remotive URL wherever its jobs appear. Each Remotive job keeps that URL as
  `source_url`; every job the search API returns carries `source` and `source_url`, and
  the screens that show jobs will display "Source: Remotive" with the link.

## Search

`POST /api/v1/search` (signed in): a query and/or a profile (skills, years, preferences)
plus typed dealbreakers. Pipeline: dealbreakers in SQL → BM25 and pgvector (HNSW,
iterative scan) → reciprocal rank fusion → fp32 cross-encoder on the fused top 10 at 128
tokens (interactive profile; the daily digest uses 30 at 256) → personalised re-score.
Each result carries its stage ranks, scores and an explanation computed from structured
fields; the response also lists the jobs the dealbreakers ruled out, with the rule.
`POST /api/v1/search/explanation` adds a one-sentence summary from an LLM
(`qwen/qwen3.8-27b` on Groq, reasoning off), withheld if it names a skill not in the
explanation; 50 per user per day.

One interactive search: p50 304 ms, p95 372 ms. Under load (3 uvicorn workers x 4
threads, 8 CPUs): p50 698 ms with 4 searches in flight, 1,376 ms with 10. Details, the
reranker investigation and the load matrix: [docs/retrieval.md](docs/retrieval.md),
[ADR 0003](docs/decisions/0003-rerank-profiles.md).

The BM25 index is rebuilt after every ingest (`make bm25` rebuilds it alone).

### Keeping jobs fresh

The worker ingests every source daily at 03:00 India time, then embeds what changed and
rebuilds BM25. When the worker starts and the last successful ingest is more than 24 h
old, it queues one catch-up ingest. A Redis lock keeps the scheduled run, a catch-up and
a manual `make ingest` from ever overlapping. `GET /api/v1/jobs/freshness` (and
`pool.updated_at` in every search) says when the pool was last updated; `/metrics` has
the same as `ingest_last_success_timestamp_seconds`. Results carry `posted_at` and
`first_seen_at`, and the `posted_within_days` dealbreaker filters on the posting date.

If your `.env` was copied from `.env.example` before this change, it still says
`INGEST_CRON_ENABLED=false` and `INGEST_CRON_HOURS=3,15` (then UTC). Delete those lines or
set them to the new values, or the schedule stays off.

## Known limitations

- There is no resume handling yet, so a search's profile and dealbreakers are sent with
  each request (see "Search"). There is no search screen yet; the API is complete.
- Search ranking weights and the interactive rerank setting are interim until the Phase 4
  eval; the reranker is the slowest stage by far and makes the API CPU-bound under load.
- The match sentence runs on `qwen/qwen3.8-27b`, a Groq **preview** model that may be
  withdrawn at short notice; the API's startup check then disables it and logs an error
  (fallback: `GROQ_FAST_MODEL=openai/gpt-oss-20b`, `GROQ_FAST_REASONING_EFFORT=low`). See
  [docs/free-tier.md](docs/free-tier.md).
- Remotive's free feed is small by design: 17 jobs in total on 2026-11-17 by its own count.
- Near-duplicate hiding is off (see "Dedup"). On the 2026-11-20 pool it had marked 2,470
  distinct roles as duplicates; those marks were cleared on 2026-11-21.
- Boilerplate stripping is frequency-based: a role-specific paragraph shared by 30% of a
  company's postings (for example one team's description) is removed too, and companies
  with fewer than 5 distinct postings are not stripped. After stripping, 81% of job cards
  are still longer than 512 tokens, so the end of the role text is truncated. See
  [docs/embedding-text-v2.md](docs/embedding-text-v2.md).
- A full embedding is slow on CPU: re-embedding 12,382 jobs took 50.5 minutes (4.1 jobs/s)
  on 2026-11-21. Later runs only embed jobs whose card changed.
- Eligibility rules cover English phrasing only, and a location that names no place
  ("Remote") stays unknown unless another field or the description decides it.
- The only real LLM calls so far are the match sentence on Groq
  (`openai/gpt-oss-120b` on 2026-11-21, `qwen/qwen3.8-27b` from 2026-11-24).
- Embeddings are fp32 from 2026-11-24 (int8 vectors depended on their ingest batch);
  `docs/retrieval.md` has the measurements. The Gemini adapter's JSON mode is unverified until a key is available
  (see `docs/free-tier.md`).
- The production Compose file, deploy guide, Langfuse tracing and Sentry come in later
  phases, as planned.
