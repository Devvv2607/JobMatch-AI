# JobMatch AI

A career agent that reads a large pool of job postings and gives a candidate the few that
fit, each with the reason and the gaps. It then tailors the resume for the roles they
choose, with every claim traced back to the original resume, and preps them for the
interview.

**Status: Phase 1 of 10 (foundation).** Accounts, sessions, the API skeleton, the LLM
client, observability and CI exist. Ingestion, retrieval, matching and every
product screen are still to come; see [PLAN.md](PLAN.md). This README reports no quality
or latency metrics yet, because none have been measured.

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

## Known limitations

- Only accounts and sessions exist; there are no jobs, matches or resumes yet.
- No LLM call has been made against a real provider. The Gemini adapter's JSON mode is
  unverified until a key is available (see `docs/free-tier.md`).
- The production Compose file, deploy guide, Langfuse tracing and Sentry come in later
  phases, as planned.
