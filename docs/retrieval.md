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
  → cross-encoder on the fused top 30                                  ml/reranker.py
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

ms-marco-MiniLM-L6-v2, exported to int8 ONNX at image build time; the build fails unless
the int8 model's scores correlate with Sentence Transformers' fp32 CrossEncoder
(Pearson 0.9999 over 12 pairs, same best passage for 3 queries). It reads the query and
a passage of title, skills and the start of `search_text`, truncated to
`RERANK_MAX_TOKENS` (default 256).

**Pairs are scored one at a time.** With dynamic int8 quantisation onnxruntime picks the
activation scale from the whole input tensor, so in a padded batch a job's score depended
on the other jobs in the batch. Measured on 30 postings × 5 queries: up to 0.49 logit
apart (mean 0.08), and 12 of the 50 top-10 positions changed. Scoring separately is
deterministic and was also faster (1.38 s vs 1.60 s for 30 pairs at 256 tokens), since no
pair is padded to the longest.

Both models run on one dedicated thread per API process: concurrent searches queue for
it rather than oversubscribing the CPU.

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
included. `max_tokens` is 1024 because gpt-oss on Groq counts reasoning against it (at
200 its JSON was cut off).

## Ruled out

The same query is retrieved again without the dealbreakers (BM25 and vector over the
pool, fused); whatever the filter removed from that list is returned best first (at most
20), each with every rule that excluded it, `violates` or `unknown` (strict) plus the
reason.

## Caching

Responses are cached per user for 300 s in Redis. The key includes the BM25 index
version, which changes on every ingest, so cached results never span two pools. A cached
response is marked `cached: true` and carries the timings of the search that produced it.

## Latency

LATENCY_PLACEHOLDER

## Known gaps

- Ranking quality is unmeasured until the Phase 4 labelled set; weights, candidate counts
  and reranker settings are defaults.
- The reranker dominates latency (see above); the 300 ms target from PLAN.md is not met
  with the planned settings on this machine.
- The profile and dealbreakers are sent with every request until resume parsing and
  stored profiles exist (Phase 5).
- Experience fit uses fixed bands and title-derived levels; titles without a level count
  as mid.
