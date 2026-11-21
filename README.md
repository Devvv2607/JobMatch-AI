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
- **Embeddings:** `bge-small-en-v1.5`, quantised to 8-bit ONNX at image build time and
  run with onnxruntime, with no PyTorch at runtime. The input is a "job card": title,
  level, skills, location, then `search_text`, truncated at 512 tokens. The recipe is
  versioned (`EMBED_TEXT_VERSION`); only jobs whose card changed are re-embedded, and a
  version change re-embeds all of them.
- **Remotive attribution:** Remotive's terms require naming Remotive and linking to the
  job's Remotive URL wherever its jobs appear. Each Remotive job keeps that URL as
  `source_url`; the screens that show jobs (from Phase 3) display "Source: Remotive" with
  the link.

## Known limitations

- There is no search, matching or resume handling yet.
- Remotive's free feed is small by design: 17 jobs in total on 2026-11-17 by its own count.
- **Near-duplicate detection over-merges (open, awaiting a decision).** On the 2026-11-20
  pool it marked 2,470 jobs as near-duplicates, but sampled pairs are distinct roles: job
  text truncated to 512 tokens is dominated by each company's boilerplate. It hides 290
  India-eligible jobs (1,339 eligible with exact dedup only, 1,049 with near-duplicates).
- A full first embedding is slow on CPU: 11,700 jobs took 69 minutes (2.8 jobs/s).
  Later runs only embed new or changed jobs (1,247 jobs in 7 minutes on 2026-11-20).
- Eligibility rules cover English phrasing only, and a location that names no place
  ("Remote") stays unknown unless another field or the description decides it.
- No LLM call has been made against a real provider. The Gemini adapter's JSON mode is
  unverified until a key is available (see `docs/free-tier.md`).
- The production Compose file, deploy guide, Langfuse tracing and Sentry come in later
  phases, as planned.
