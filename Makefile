# Every target is one command, also written out in the README, so nothing depends on make.

.PHONY: up down reset logs ps test test-all lint typecheck migrate openapi fe-check ingest ingest-embed ingest-report check-boards bm25 bench-search backup backup-check discover dedup-review eval-profiles label label-demo snapshot pool judge cowork-export cowork-import

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

test:      ## Fast backend tests, 4 in parallel (skips @slow: real models, ingest runs)
	docker compose run --rm api pytest -n 4 -m "not slow"

test-all:  ## Every backend test, 4 in parallel, with coverage (what CI runs)
	docker compose run --rm api pytest -n 4 --cov=app --cov-report=term-missing

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

eval-profiles: ## Validate and list the 25 fictional eval profiles (eval/profiles)
	docker compose run --rm --no-deps ingest python -m app.eval.cli profiles

label-demo: ## Throwaway sample (random jobs, FAKE judge labels) in eval/labels/demo, then the tool
	docker compose run --rm --no-deps ingest python -m app.eval.cli demo --set demo
	docker compose run --rm --no-deps -p 127.0.0.1:8765:8765 ingest python -m app.eval.cli label --set demo --blind 4 --host 0.0.0.0

snapshot:  ## Freeze the eval pool: make snapshot ID=<id> DUMP=backups/<file>.dump
	MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -v ./backups:/backups:ro ingest python -m app.eval.cli snapshot --id $(ID) --dump /$(DUMP) --commit $$(git rev-parse HEAD)

pool:      ## Run every variant on a snapshot and pool 20 pairs per profile: make pool SET=<name> ID=<id>
	docker compose run --rm --no-deps ingest python -m app.eval.cli pool --set $(SET) --snapshot $(ID)

judge:     ## LLM-judge a label set (resumable): make judge SET=<name> [ARGS="--sample 10"]
	docker compose run --rm --no-deps ingest python -m app.eval.cli judge --set $(SET) $(ARGS)

cowork-export: ## Claude Cowork grading sheets in eval/private/cowork/: make cowork-export SET=<name>
	docker compose run --rm --no-deps ingest python -m app.eval.cli cowork-export --set $(SET)

cowork-import: ## Check and import one filled sheet: make cowork-import SET=<name> FILE=private/cowork/batch-01.xlsx
	docker compose run --rm --no-deps ingest python -m app.eval.cli cowork-import --set $(SET) --file $(FILE)

label:     ## The labelling tool on a label set: make label SET=<name>; open http://127.0.0.1:8765
	docker compose run --rm --no-deps -p 127.0.0.1:8765:8765 ingest python -m app.eval.cli label --set $(SET) --host 0.0.0.0
