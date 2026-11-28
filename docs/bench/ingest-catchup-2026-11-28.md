# Catch-up ingest, 2026-11-28 (run 94b960bc): log excerpt

Extracted from `docker compose logs --no-log-prefix worker` on 2026-11-28 (the worker container's log, lost when the container is recreated) for the source findings and the Himalayas "before" numbers in docs/briefs/backlog-from-phase-4.md. URLs and statuses only; no headers or keys.

## Run and per-source summary lines
```
{"ts": "2026-11-28T10:23:14.303+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "ingest run started", "request_id": null, "run_id": "94b960bc-2627-4749-939d-de6ff9d88ffd", "sources": ["greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "remotive", "himalayas", "adzuna"]}
{"ts": "2026-11-28T10:30:16.866+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "source ingested", "request_id": null, "source": "greenhouse", "status": "running", "boards_ok": 71, "boards_failed": 0, "fetched": 10231, "new": 202, "updated": 100, "unchanged": 9929, "expired": 60, "skipped": 0, "peak_rss_mib": 632}
{"ts": "2026-11-28T10:30:53.448+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "source ingested", "request_id": null, "source": "lever", "status": "running", "boards_ok": 14, "boards_failed": 0, "fetched": 867, "new": 29, "updated": 20, "unchanged": 818, "expired": 2, "skipped": 0, "peak_rss_mib": 632}
{"ts": "2026-11-28T10:33:38.019+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "source ingested", "request_id": null, "source": "ashby", "status": "running", "boards_ok": 60, "boards_failed": 1, "fetched": 4884, "new": 48, "updated": 68, "unchanged": 4768, "expired": 9, "skipped": 0, "peak_rss_mib": 681}
{"ts": "2026-11-28T10:34:08.500+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "source ingested", "request_id": null, "source": "smartrecruiters", "status": "running", "boards_ok": 7, "boards_failed": 0, "fetched": 173, "new": 6, "updated": 1, "unchanged": 166, "expired": 4, "skipped": 0, "peak_rss_mib": 681}
{"ts": "2026-11-28T10:34:08.509+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "source ingested", "request_id": null, "source": "workable", "status": "skipped", "boards_ok": 0, "boards_failed": 0, "fetched": 0, "new": 0, "updated": 0, "unchanged": 0, "expired": 0, "skipped": 0, "peak_rss_mib": 681}
{"ts": "2026-11-28T10:34:08.517+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "source ingested", "request_id": null, "source": "recruitee", "status": "skipped", "boards_ok": 0, "boards_failed": 0, "fetched": 0, "new": 0, "updated": 0, "unchanged": 0, "expired": 0, "skipped": 0, "peak_rss_mib": 681}
{"ts": "2026-11-28T10:34:09.167+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "source ingested", "request_id": null, "source": "remotive", "status": "running", "boards_ok": 1, "boards_failed": 0, "fetched": 16, "new": 2, "updated": 0, "unchanged": 14, "expired": 0, "skipped": 0, "peak_rss_mib": 681}
{"ts": "2026-11-28T10:52:54.000+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "source ingested", "request_id": null, "source": "himalayas", "status": "running", "boards_ok": 1, "boards_failed": 0, "fetched": 6909, "new": 418, "updated": 277, "unchanged": 6214, "expired": 158, "skipped": 0, "peak_rss_mib": 681}
{"ts": "2026-11-28T10:54:45.163+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "source ingested", "request_id": null, "source": "adzuna", "status": "running", "boards_ok": 1, "boards_failed": 0, "fetched": 1500, "new": 74, "updated": 6, "unchanged": 1420, "expired": 0, "skipped": 0, "peak_rss_mib": 681}
{"ts": "2026-11-28T11:00:23.515+00:00", "level": "INFO", "logger": "app.ingest.runner", "msg": "ingest run finished", "request_id": null, "run_id": "94b960bc-2627-4749-939d-de6ff9d88ffd", "seconds": 2229.2, "stale": 0, "embedded": 1362, "duplicates": {"content_hash": 104, "cross_source": 179, "near_duplicate_text": 735, "text_buckets_skipped": 0}, "statuses": {"greenhouse": "succeeded", "lever": "succeeded", "ashby": "partial", "smartrecruiters": "succeeded", "workable": "skipped", "recruitee": "skipped", "remotive": "succeeded", "himalayas": "succeeded", "adzuna": "succeeded"}, "errors": [], "peak_rss_mib": 1066}
```

## Ashby non-200 responses
```
{"ts": "2026-11-28T10:30:56.665+00:00", "level": "INFO", "logger": "httpx", "msg": "HTTP Request: GET https://api.ashbyhq.com/posting-api/job-board/bio?includeCompensation=true \"HTTP/1.1 404 Not Found\"", "request_id": null}
```

## Himalayas search requests

Requests: 362; by status:
```
    347 HTTP/1.1 200 OK
     15 HTTP/1.1 429 Too Many Requests
```
First and last request:
```
{"ts": "2026-11-28T10:34:09.697+00:00", "level": "INFO", "logger": "httpx", "msg": "HTTP Request: GET https://himalayas.app/jobs/api/search?country=IN&page=1 \"HTTP/1.1 200 OK\"", "request_id": null}
{"ts": "2026-11-28T10:50:00.967+00:00", "level": "INFO", "logger": "httpx", "msg": "HTTP Request: GET https://himalayas.app/jobs/api/search?country=IN&page=347 \"HTTP/1.1 200 OK\"", "request_id": null}
```

Recompute (PowerShell): docker compose logs --no-log-prefix worker | Select-String 'himalayas.app/jobs/api/search' | Measure-Object
