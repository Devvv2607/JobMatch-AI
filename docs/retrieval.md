# Retrieval (Phase 3)

`POST /api/v1/search` turns a query and/or a candidate profile into a short ranked list,
each job with its scores and a computed explanation, plus the jobs the dealbreakers ruled
out and why. `POST /api/v1/search/explanation` adds an optional one-sentence summary
written by an LLM from that explanation. Code: `backend/app/retrieval/`.

```
request (query and/or profile, dealbreakers)
  → dealbreakers (SQL)                       → allowed job ids        filters.py, rules.py
  → BM25 top 100, masked to allowed ids      ∥ vector top 100, same WHERE   bm25.py, vector.py
  → reciprocal rank fusion (k = 60)                                    scoring.py
  → cross-encoder on the fused top M (profile: 10 interactive, 30 digest) ml/reranker.py
  → personalised re-score → top `limit` (≤ 30) with explanations       scoring.py
  + ruled-out list, pool counts, per-stage timings                     service.py
```

## Dealbreakers

Each dealbreaker is a typed rule (`kind` + its fields, optional `strict`) that compiles to
one SQL expression, its *outcome*: `pass`, `unknown` (the posting does not say) or
`violates`. The filter keeps `pass` and, unless the rule is strict, `unknown`; the
ruled-out labels and the pool counts are read from the same expression, so the list of
excluded jobs and the reason given for each cannot disagree with what the filter did. A
test checks this for every combination of five rules.

| kind | fields | unknown when |
|---|---|---|
| `work_eligibility` | `country` (ISO code or name) | the posting does not say where the job can be done from |
| `workplace` | `allowed`: remote / hybrid / onsite | remote policy not stated |
| `min_salary_usd` | `amount` (annual USD; the top of the posted range is compared) | no salary listed |
| `seniority` | `allowed` levels | never (levels come from the title; no marker = mid) |
| `employment_type` | `allowed` types | never |
| `exclude_industries` | `industries` (tags from `companies.yaml`) | the company has no industry tags |
| `exclude_companies` | `companies` (names, compared by slug) | never |

Unknown + not strict: the job stays and its explanation lists a *flag* naming the rule and
what is missing. Every search starts from the same pool: not expired, not a duplicate.

## BM25

[bm25s](https://github.com/xhluska/bm25s) over title, skills and `search_text` (the
description with company boilerplate removed: the same text the vectors were built
from), lower-cased, English stopwords, Snowball stemming; `c++`, `c#` and `.net`-style
tokens survive. The index is rebuilt in full after every ingest (and `make ingest-embed`,
`make bm25`), written to a staging directory on the shared `bm25data` volume, renamed
into place, and its version published in Redis. Each API process checks the version at
most every 2 s and swaps to the new index with one assignment; a search already running
finishes on the index it started with. The two newest versions are kept.

On 2026-11-21: 11,531 documents, 9.2 s for the whole rebuild including the database
read, 24 MB on disk. "Incremental" in PLAN.md §4.1 meant incremental tokenising; at this
size a full rebuild is fast enough that it was not needed.

The mask is applied inside bm25s (`weight_mask`), so excluded jobs score 0; zero-score
hits are dropped, since bm25s still returns k rows when fewer than k match.

If no index has been published yet, search runs vector-only and says so in
`degraded: ["bm25_unavailable"]`.

## Vector search

pgvector HNSW (cosine) on the one-vector-per-job embeddings from Phase 2, queried with
bge's query instruction. The WHERE clause is the same `allowed(rules)` expression as the
filter. `hnsw.iterative_scan = relaxed_order` (pgvector 0.8.7) keeps scanning until 100
rows pass the filter; results are re-sorted by distance in Python since relaxed order
may return them slightly out of order. `ef_search` = 100.

What the planner does (EXPLAIN ANALYZE, full plans in the benchmark report):

- **No dealbreakers:** HNSW index scan, 11.1 ms for the top 100.
- **Selective dealbreakers** (India-eligible + remote, strict: 198 of 11,531 jobs): the
  planner skips the index and does an exact scan and sort, 14.8 ms. Its row estimate is
  1 because it cannot see inside the rule CASE expressions; here that leads to the
  better plan (exact results, no recall loss). Whether a mid-selectivity filter ever
  picks the index and returns fewer rows is not yet measured.

## Rerank

ms-marco-MiniLM-L6-v2, exported to **fp32 ONNX** at image build time (91 MB). The build
fails unless the runtime matches Sentence Transformers' PyTorch CrossEncoder within 0.01
logit (measured: 0.000006) **and** a pair scores the same batched and alone within 0.01
(measured: 0.000000). It reads the query and a passage of title, skills and the start of
`search_text`, truncated per profile. Pairs are sorted by length and run in batches of 8.

**Why fp32.** The first version used int8 (dynamic quantisation). Its scores depended on
the batch: onnxruntime picks each activation's scale from the whole input tensor, so a
job's logit moved by up to 0.46 with its neighbours and padding. Tested on 30 real
passages x 10 queries, 8 CPUs ([report](bench/rerank-variants-2026-11-23.md)):

| variant | max abs(d) batched vs alone (128 / 256 tok) | top-10 overlap vs PyTorch (256 tok) | 10@128 fastest | 30@256 fastest |
|---|---|---|---|---|
| fp32 | 0.0 / 0.0 | 1.00 | 161 ms (batch) | 1,149 ms (sorted batches) |
| int8 dynamic | 0.46 / 0.44 | 0.93 | 198 ms (one at a time) | 1,092 ms (one at a time) |
| int8 static (per-channel) | 0.0 / 0.57 | 0.92 | 117 ms (batch, but inconsistent) | 771 ms (inconsistent) |

Static int8 looked consistent at 128 tokens only because every passage filled 128 tokens,
so nothing was padded; at 256 tokens the mask's large negative values are clipped by the
fixed activation scale and padding leaks in. `attention_mask` and `token_type_ids` were
checked and are passed.

fp32 is exact and the fastest consistent variant for one interactive search. Under load
it costs more CPU than int8 one-at-a-time (53.6 vs 41.3 ms per pair at 128 tokens, one
thread), so int8-one-at-a-time is listed as a Phase 4 candidate: about 25% more
throughput if its NDCG holds up.

### Rerank profiles ([ADR 0003](decisions/0003-rerank-profiles.md))

| profile | top | tokens | used by |
|---|---:|---:|---|
| interactive | 10 (interim) | 128 | `POST /search` |
| digest | 30 | 256 | the offline Today list |

Results beyond the reranked head follow in fused order (`rerank_logit: null`), so
`limit` can exceed `top`; `top = 0` is no rerank. The response says which profile ran
(`rerank_profile`) and how many jobs it scored (`reranked`). Phase 4 chooses the final
interactive setting from NDCG vs latency for no rerank, 10@128, 20@128 and 30@256.

### Threads and workers

Both models run on one dedicated thread per API process, with onnxruntime's intra-op
threads set by `RERANKER_THREADS` / `EMBEDDING_THREADS` and not spin-waiting. The API
runs 3 uvicorn workers x 4 threads, chosen from a load matrix (below). Each worker builds
its engine once; an earlier sync dependency raced and built one per concurrent first
request (1.8 GB per worker).

## Re-score

Components, each in [0, 1]:

| component | value | weight |
|---|---|---|
| rerank | sigmoid of the cross-encoder logit | 0.6 |
| skills | posting skills the candidate has / posting skills (canonical taxonomy names) | 0.25 |
| experience | 1 inside the level's years band (e.g. senior 5–10), −0.25 per year outside | 0.1 |
| preferences | per stated preference (workplace, countries, levels): 1 match, 0 mismatch, 0.5 posting silent; averaged | 0.05 |

Final score = weighted mean of the components available for that job; a component with
no data (no profile skills, a posting with no skills listed, no years given) is left out
rather than counted as 0. Weights live in config and are **untuned until the Phase 4
eval**.

## Explanation

Computed from structured fields only, never from description text: skills matched and
missing, experience band and fit, each stated preference with match / mismatch / unknown,
and dealbreaker flags. Every statement maps to a column.

The optional sentence (`/search/explanation`) sends that object, and nothing else, to
the LLM as data class "personal" (Groq or Ollama only). If the sentence names a taxonomy
skill that is not in the object's matched or missing lists, it is withheld
(`status: dropped`) and the client shows the computed explanation. The server recomputes
the explanation from the job id; a client cannot supply one. Each request that reaches
the LLM step counts against `LLM_DAILY_QUOTA_PER_USER` (50 per UTC day), cache hits
included.

The model is `GROQ_FAST_MODEL` = `qwen/qwen3.8-27b` with `reasoning_effort: none`, at
`max_tokens` 200. Reasoning models count reasoning against `max_tokens` (gpt-oss-120b
was cut off at 200: `json_validate_failed`). This account's `/models` lists no Llama
models; `allam-2-7b` hit its rate limit at 15 calls and returned invalid JSON once. On 20
real explanations Qwen gave 20 valid sentences, none dropped, p50 253 ms, p95 451 ms, and
at most 49 completion tokens. Groq's headers give this account 1,000 requests/day and
8,000 tokens/minute for it, so the 50-per-user quota covers about 20 users a day.

## Ruled out

The same query is retrieved again without the dealbreakers (BM25 and vector over the
pool, fused); whatever the filter removed from that list is returned best first (at most
20), each with every rule that excluded it, `violates` or `unknown` (strict) plus the
reason.

## Caching

Allowed ids and pool counts depend only on the dealbreakers and the pool, so each API
process caches them per (BM25 index version, dealbreakers); the version changes at every
ingest. This took ~50 ms off every search.

Responses are cached per user for 300 s in Redis. The key includes the BM25 index
version, which changes on every ingest, so cached results never span two pools. A cached
response is marked `cached: true` and carries the timings of the search that produced it.

## Latency

Hardware for every number here: laptop (Ryzen 7 7445HS, mains power), Docker Desktop
WSL2 with 8 CPUs and 6 GB, Postgres in the same VM; 11,531-job pool. Milliseconds.

**One search at a time** (`make bench-search`, in-process, cache off, onnxruntime 4
threads; full report and EXPLAIN plans in [bench/search-2026-11-24.md](bench/search-2026-11-24.md)).
60 searches per profile: 20 queries x 3 dealbreaker sets, each with a profile.

| stage | interactive (10@128) p50 | p95 | digest (30@256) p50 | p95 |
|---|---:|---:|---:|---:|
| filter (cached allowed ids + counts) | 0.1 | 0.1 | 0.1 | 0.2 |
| embed_query | 15.6 | 22.6 | 15.9 | 24.2 |
| bm25 | 5.4 | 17.6 | 6.0 | 16.7 |
| vector | 15.2 | 29.9 | 15.9 | 30.8 |
| fuse | 0.2 | 0.3 | 0.2 | 0.3 |
| load | 5.6 | 8.8 | 9.6 | 19.0 |
| rerank | 243.9 | 268.3 | 1,507.1 | 1,898.4 |
| rescore | 0.5 | 0.9 | 1.4 | 3.3 |
| ruled_out (40 searches with dealbreakers) | 20.0 | 31.1 | 20.8 | 39.9 |
| **total** | **304.3** | **371.6** | **1,583.4** | **2,013.5** |

The filter row is the cached case. The first search for a dealbreaker set after an ingest
also runs the allowed-ids and counts queries (~50 ms: 19 + 31 ms measured before the
cache).

Phase 4 candidates, same run (total p50 / p95): no rerank 62 / 75; 10@128 292 / 331;
20@128 506 / 593; 30@256 1,588 / 1,817.

**Under load** (HTTP, `scripts/load_search.py`, interactive profile, cache off; full
matrix in [bench/load-2026-11-24.md](bench/load-2026-11-24.md)):

| workers x threads | peak memory | 4 in flight p50 / p95 | 10 in flight p50 / p95 | searches/s at 10 |
|---|---:|---:|---:|---:|
| 1 x 4 | 341 MiB | 1,055 / 1,278 | 2,455 / 2,559 | 4.0 |
| 2 x 4 | 703 MiB | 887 / 1,133 | 1,318 / 2,618 | 5.7 |
| **3 x 4 (chosen)** | **811 MiB** | **698 / 782** | **1,376 / 2,728** | **5.5** |

At 10 in flight the API uses all 8 CPUs; the ceiling is the fp32 reranker's ~0.6
core-seconds per search. Before this phase's fixes the same test (then 4 CPUs, int8, 30@256,
one worker) gave p50 6.3 s at 4 in flight.

The 300 ms target from PLAN.md is narrowly missed for one interactive search (p50
304 ms, p95 372 ms) and clearly missed under concurrency.

## Known gaps

- Ranking quality is unmeasured until the Phase 4 labelled set; weights, candidate counts
  and reranker settings are defaults.
- The reranker dominates latency and CPU (see "Latency"). At 10 searches in flight the
  API is CPU-bound: about 0.6 core-seconds of fp32 reranking per search.
- ~~The embedder is still dynamic int8~~ Fixed in Phase 3b: the embedder is fp32
  (int8 vectors moved by up to 0.0079 in 1 - cos with their ingest batch; fp32 4.7e-8),
  and the model variant is part of the embedding hash. All 11,736 current jobs were
  re-embedded on 2026-11-24 in 46 min ([report](bench/embedder-variants-2026-11-24.md)).
- The profile and dealbreakers are sent with every request until resume parsing and
  stored profiles exist (Phase 5).
- Experience fit uses fixed bands and title-derived levels; titles without a level count
  as mid.
