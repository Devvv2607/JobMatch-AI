# Backlog from the Phase 4 evaluation

Recorded 2026-11-27 (owner decisions). Each item is built in the phase named, as part of
that phase's brief. The numbers come from eval/report.md, section 7a.

## Phase 5: freshness filter and stale signal in ranking

The snapshot's searchable pool has many old postings: 26.2% older than 90 days and 9.9%
older than 365. By source, Adzuna has 51.4% over a year, Lever 25.1%, Greenhouse 13.0%
and Himalayas 0. Among the 1,000 eval pairs, 20% are older than 90 days and 10% older
than 365.

- Demote postings older than 90 days in the ranking, and hide those older than 365
  days unless the posting is `is_evergreen`. Search already ranks postings over a year
  old after fresher ones (commit a1ff864); this item extends that into a measured rule.
- Show the age as a signal on the result ("posted 4 months ago").
- Measure before switching it on: the Phase 4 harness reports the main metrics on all
  pairs and on pairs posted within 90 days. Any ranking change goes through the CI gate
  and the eval report.
- An old `posted_at` on an ATS board may be a re-opened or evergreen requisition rather
  than a dead job. Combine age with the ghost-job signal already in the Phase 5 backlog.

## Phase 5 (or the next ingest change): dedup keeps the newest posting

Today the canonical posting of a merged group is the best source quality, then the
**earliest seen**, then `posted_at` (`app/ingest/dedup.py`: the exact-duplicate SQL
`ORDER BY {rank}, first_seen_at, posted_at` and `Posting.order()`). In the Coinbase #13
case (`72deffe2…` kept, `e413f65b…` merged), the merged job shows the older posting's pay
range (max $197,010), while the newer opening's $218,900 survives only on the hidden row.

- Rule: source quality first (unchanged), then the most recently posted, falling back to
  the most recently updated, then id. The newest pay range and text then win.
- Change both places, add a test with two postings that differ only in date and salary,
  and record the rule in the decision log.
- Not applied now because dedup recomputes `duplicate_of` on every ingest: the next
  automatic run would flip the canonical id of existing groups in the live pool (and
  hide the previously visible copy). Ship it with a one-off migration note, a dry run
  showing how many groups change canonical, and a check that saved jobs pointing at a
  now-duplicate id are redirected to the canonical one.

## After Phase 4: operations (owner, 2026-11-27)

- **Restart policies and healthchecks for every compose service** (api, worker, db,
  redis): today db and redis have none in docker-compose.yml. On 2026-11-27 they were set
  to unless-stopped by `docker update` on the running containers only, so a `docker
  compose up` that recreates them drops it again. Put it in the compose file.
- **Alert when the worker or the daily ingest has not run for more than 26 h** (e.g.
  from the last successful ingest_runs row, exported as a metric and alerted in
  Prometheus/Grafana, or checked by the API's readiness report).
- **Find out why the worker stopped around 10:00 IST on 2026-11-27** (exited 255, the
  same as the api and frontend containers earlier): check `docker logs
  jobmatch-worker-1`, Docker Desktop's logs and Windows' event log for that time (a WSL
  or Docker Desktop restart under memory pressure is the likely cause; the session's
  background shells were reaped for low memory at 14:16 the same day).

### Catch-up ingest of 2026-11-28: source findings (read-only, dev-setup)

Run `94b960bc` (worker catch-up, 10:23-11:00 UTC, 2,229 s, 1,362 embedded, no errors).
Evidence: the worker log excerpt in `docs/bench/ingest-catchup-2026-11-28.md`.
- **Ashby `partial`**: 60 of 61 boards fetched; the one failure is board `bio` ("Bio",
  from Common Crawl discovery, `companies_discovered.yaml`), which returns **HTTP 404**
  (checked again by hand the same day). The board was removed or renamed: not a rate
  limit or an API change. Fix: drop or re-verify the entry; consider marking a board
  that 404s on N runs in a row as gone instead of making the source `partial` forever.
- **Workable and Recruitee `skipped`**: by design. Zero boards are configured for either
  ("no boards configured for this source"; adapters built and tested). Common Crawl
  discovery stopped at 400 boards in index order and probably never reached their prefixes
  (`docs/bench/sources-2026-11-24.md`). Fix: `make discover SOURCE=commoncrawl` with a
  per-ATS limit, then verify boards as usual.

### Incremental Himalayas ingest (app code: its own branch, not dev-setup)

**Approved 2026-11-28:** a small branch after 5a merges and before 5c. Scope: the read-only `sort=recent` check first; the expiry safety rule; remove the dead Ashby board `bio`; report why Workable/Recruitee have no boards (should discovery have found some?); measure before/after.

**Before** (same run, measured from the worker log, `docs/bench/ingest-catchup-2026-11-28.md`): `country=IN`, 347 pages of 200 OK
plus **15 HTTP 429s** (retried), first request 10:34:09.7, last 10:50:01.0 UTC = **15 min 51 s** (43% of the
whole ingest). 6,909 jobs fetched: 418 new, 277 updated, **6,214 unchanged (90%)**, 158
expired.

**What Himalayas documents** (https://himalayas.app/docs/remote-jobs-api, read
2026-11-28):
- search takes `sort` (`relevant`, `recent`, ...). Without `q`, the default order is
  "recent activity, not pubDate", and `recent` itself is not defined;
- there is no updated-since filter;
- unkeyed calls share one public allowance with no number given. A free key gets 60/min
  and 10,000 a day;
- 429s carry `Retry-After`; search responses are cached up to an hour;
- results can shift between pages, so dedupe on `guid`.

**Design:**
1. Daily runs page `sort=recent` and stop after N (start with 3) consecutive pages
   where every job is already stored with the same content hash. A cap (e.g. 60 pages)
   applies as well.
2. A **weekly full sweep** walks every page, as now.
3. **Expiry:** an incremental run sees only part of the feed, so it must not count
   missing jobs toward expiry (today a job expires after missing two successful runs).
   Only full sweeps count misses; `expiryDate` and the expired flag still apply daily.
4. Keep 1 request a second, honour `Retry-After`, and take a free API key if the owner
   wants one (`.env`, never in chat).
5. Verify first, read-only: is `sort=recent` really newest-first and stable across
   pages? Fetch pages 1-3 twice, an hour apart, and compare.

**Measure after:** pages, 429s, run time and new/updated counts for a daily run against
the same day's full sweep. Success: new and updated jobs within 1% of the full sweep's,
in a fraction of the pages.
