# Every target is one command, also written out in the README, so nothing depends on make.

.PHONY: up down reset logs ps test lint typecheck migrate openapi fe-check ingest ingest-embed ingest-report check-boards bm25 bench-search backup backup-check discover dedup-review

up:        ## Build and start the whole stack
	docker compose up -d --build

down:      ## Stop the stack, keep data
	docker compose down

reset:     ## Stop the stack and delete all data volumes
	docker compose down -v

logs:      ## Follow api and worker logs
	docker compose logs -f api worker

ps:        ## Service status
	docker compose ps -a

test:      ## Backend tests with coverage (uses a separate *_test database)
	docker compose run --rm api pytest --cov=app --cov-report=term-missing

lint:      ## Ruff lint and format check
	docker compose run --rm --no-deps api sh -c "ruff check . && ruff format --check ."

typecheck: ## Mypy, strict
	docker compose run --rm --no-deps api mypy app tests scripts

migrate:   ## Apply database migrations
	docker compose run --rm migrate

openapi:   ## Regenerate frontend/openapi.json and the TypeScript API types
	docker compose run --rm --no-deps -T api python -m scripts.export_openapi > frontend/openapi.json && npm --prefix frontend run gen:api

ingest:    ## Fetch every source, normalise, dedup, embed (one run)
	docker compose run --rm ingest python -m app.ingest.cli run

ingest-embed: ## Embed pending jobs only (no fetching), e.g. to resume an interrupted run
	docker compose run --rm ingest python -m app.ingest.cli embed

bm25:      ## Rebuild and publish the BM25 index from the current pool (no fetching)
	docker compose run --rm ingest python -m app.ingest.cli bm25

bench-search: ## Per-stage search latency (sequential) and under concurrency; writes docs/bench/
	docker compose run --rm -e EMBEDDING_THREADS=4 -v ./docs/bench:/out ingest python -m scripts.bench_search --out /out

backup:    ## pg_dump (custom format) of the database into backups/ (gitignored)
	sh ops/backup.sh backup

backup-check: ## Restore the newest backup into a scratch database and compare row counts
	sh ops/backup.sh check

discover:  ## Find and verify more ATS boards: make discover SOURCE=yc|elevation|commoncrawl
	docker compose run --rm -v ./backend/app/ingest/data:/app/app/ingest/data -v ./docs/bench:/out ingest python -m app.ingest.discover $(SOURCE) --report-dir /out

dedup-review: ## Sample 50 near-duplicate pairs from the live pool for hand review (read-only)
	docker compose run --rm --no-deps -v ./docs/bench:/out ingest python -m scripts.dedup_review --out /out/dedup-review.md

ingest-report: ## Pool report: totals, eligibility for an India-based candidate, rules, failures
	docker compose run --rm --no-deps ingest python -m app.ingest.cli report --country IN

check-boards: ## Check every board token in companies.yaml is live
	docker compose run --rm --no-deps ingest python -m app.ingest.cli check-boards

fe-check:  ## Frontend lint, typecheck and build
	npm --prefix frontend run lint && npm --prefix frontend run typecheck && npm --prefix frontend run build
