\pset footer off
\echo '== last run, per source'
SELECT source, status, boards_ok, boards_failed, fetched, new, updated, unchanged, expired, skipped,
       embedded, embed_pending, round(extract(epoch FROM finished_at - started_at)::numeric) AS seconds, note
FROM ingest_runs
WHERE run_id = (SELECT run_id FROM ingest_runs ORDER BY started_at DESC LIMIT 1)
ORDER BY source;

\echo '== active pool per source: India eligibility, remote, duplicates'
SELECT source,
       count(*) AS active,
       count(*) FILTER (WHERE duplicate_of IS NULL) AS unique_active,
       count(*) FILTER (WHERE duplicate_of IS NULL AND (eligibility_scope = 'worldwide' OR work_countries @> ARRAY['IN']::varchar(2)[])) AS india_eligible,
       count(*) FILTER (WHERE duplicate_of IS NULL AND eligibility_scope = 'unknown') AS india_unknown,
       count(*) FILTER (WHERE duplicate_of IS NULL AND eligibility_scope = 'listed' AND NOT work_countries @> ARRAY['IN']::varchar(2)[]) AS india_ineligible,
       count(*) FILTER (WHERE duplicate_of IS NULL AND remote_policy = 'remote' AND (eligibility_scope = 'worldwide' OR work_countries @> ARRAY['IN']::varchar(2)[])) AS remote_india_eligible
FROM jobs WHERE status != 'expired'
GROUP BY source ORDER BY active DESC;

\echo '== duplicates merged (active jobs pointing to another), by reason and source pair'
SELECT d.duplicate_reason, d.source AS duplicate_source, c.source AS kept_source, count(*)
FROM jobs d JOIN jobs c ON c.id = d.duplicate_of
WHERE d.status != 'expired'
GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC;

\echo '== salaries: parsed vs refused, per source (active, unique)'
SELECT source,
       count(*) FILTER (WHERE salary_source IS NOT NULL) AS parsed,
       count(*) FILTER (WHERE salary_source LIKE '%.salary') AS from_structured,
       count(*) FILTER (WHERE salary_source = 'description' OR salary_source LIKE '%salary_text') AS from_text,
       count(*) FILTER (WHERE salary_refusal IS NOT NULL) AS refused
FROM jobs WHERE status != 'expired' AND duplicate_of IS NULL
GROUP BY source ORDER BY source;

\echo '== refusal reasons'
SELECT salary_refusal, count(*) FROM jobs
WHERE status != 'expired' AND duplicate_of IS NULL AND salary_refusal IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC;

\echo '== discovered companies with jobs in the pool, by discovered_via'
SELECT c.discovered_via, count(DISTINCT c.id) AS companies, count(j.id) AS active_jobs,
       count(j.id) FILTER (WHERE j.duplicate_of IS NULL AND (j.eligibility_scope = 'worldwide' OR j.work_countries @> ARRAY['IN']::varchar(2)[])) AS india_eligible
FROM companies c LEFT JOIN jobs j ON j.company_id = c.id AND j.status != 'expired'
GROUP BY 1 ORDER BY 2 DESC;

\echo '== board failures in the last run'
SELECT source, f->>'board' AS board, left(f->>'error', 90) AS error
FROM ingest_runs, jsonb_array_elements(failures) AS f
WHERE run_id = (SELECT run_id FROM ingest_runs ORDER BY started_at DESC LIMIT 1)
ORDER BY source, board;
