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
