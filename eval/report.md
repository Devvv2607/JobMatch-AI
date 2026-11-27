# JobMatch AI: Phase 4 evaluation report (eval-2026-11-25)

**Status: skeleton.** Method, judges, agreement and limitations are written; metric
tables are placeholders until the depth-10 fill is judged. The numbers will come from
`make eval FULL=1`, which writes `eval/reports/<date>-<commit>.md` and `.json`. This
page quotes that file and links to it.

**Every relevance number here is LLM-judged (Gemini). There are no human relevance labels.**

## 1. What is measured

Search quality for 25 fictional job seekers on a frozen snapshot of the job pool,
comparing the stages of the search pipeline (`backend/app/retrieval/service.py`):

| Step | Variant | What it adds |
|---|---|---|
| keyword | `bm25` | BM25 over title, skills, locations and the stripped description |
| vector | `vector` | cosine search over one embedding per job (pgvector HNSW) |
| hybrid | `fused` | reciprocal-rank fusion of the two (k = 60) |
| +personalisation | `rescore` | the personalised re-score of the fused candidates (no cross-encoder) |
| +rerank N@T | `rerank_N_T` | cross-encoder on the re-scored top N at T tokens a pair (10@128, 20@128, 30@256) |

Each variant is run in two modes: `query` (the profile's typed search plus its profile,
which is what interactive search gets) and `profile` (the profile alone, as for the daily digest).

## 2. Data

- **Snapshot** `2026-11-25` (`eval/snapshots/2026-11-25/manifest.json`): a `make backup`
  dump restored into its own database, with the BM25 index frozen; 23,705 searchable jobs.
- **Profiles**: 25 fictional candidates (`eval/profiles/`), about 70% India-based (fresher,
  1-3 and 3-6 years; ML/AI, data, backend, full-stack, product/analyst), the rest US/EU
  and remote-seeking. Each has preferences, dealbreakers and a short query. No real
  person's data.
- **Rankings**: every variant's top 30 (the API's limit) for every profile, in
  `eval/labels/eval-2026-11-25/runs.jsonl`.

## 3. Pool and the depth-10 fill

1. **Pooled pairs (500).** For each profile, 20 jobs from the union of every variant's
   top 10, best rank first, stratified so that at most half came from one source and at
   most 3 were gigs or agency postings (`app/eval/pooling.py`).
2. **The gap.** The top-10 union is 25-49 jobs per profile, so the pool left 29-39% of
   each variant's top 10 ungraded (judged@10 0.61-0.71). Counting those as grade 0
   lowered NDCG@10 by different amounts for different variants.
3. **Depth-10 fill (500 more, owner decision 2026-11-27).** `make eval-fill` added a pair
   for every job any variant ranked in its top 10 that had none (`strata.pool =
   "fill-depth10"`), built from the snapshot exactly like the pooled pairs. Gemini graded
   them. After the fill, judged@10 = {judged10_after} for every variant.
4. **Convention.** An unjudged job counts as grade 0 (primary). Condensed lists (unjudged
   jobs dropped) are shown as a check. With every top 10 judged, the two agree on NDCG@10.

## 4. The judges

All three grade every pair with the same rubric (`backend/app/prompts/eval_judge/v1.md`):
3 apply today, 2 good with gaps, 1 same field but wrong fit, 0 irrelevant; a broken
dealbreaker caps the grade at 1.

| Judge | Role | Pairs | Input |
|---|---|---:|---|
| Gemini `gemini-3.5-flash-lite` | **primary**: every reported metric | 1,000 | the rubric as system prompt, the pair as JSON (structured fields + first ~1,400 characters of the description) |
| Groq `openai/gpt-oss-120b` | agreement, robustness | 120 blind | same as Gemini |
| Claude Cowork (an AI agent) | a third judge on the **120 blind pairs only** (batches 01-04 cancelled 2026-11-27) | 120 blind (+1); the 91 cut blind pairs re-graded on input v3 in batch-05 | spreadsheets with the judge's exact candidate and job objects and the rubric; its first 118 grades came from the labelling tool's card |

The blind set is 120 stratified pooled pairs, fixed before any judge ran.

## 5. Agreement between the judges (blind pairs)

Full tables, confusion matrices and example pairs: `eval/reports/agreement-2026-11-27.md`
(`python -m app.eval.cli agreement --set eval-2026-11-25 --out reports/agreement-<date>.md`).

| Judges | n | weighted kappa [95% CI] | exact | within one | mean a - b |
|---|---:|---|---:|---:|---:|
| Gemini vs Groq | 120 | 0.697 [0.585, 0.788] | 67.5% | 97.5% | -0.22 |
| Gemini vs Cowork | 120 | 0.658 [0.550, 0.746] | 65.0% | 99.2% | -0.04 |
| Groq vs Cowork | 120 | 0.677 [0.559, 0.769] | 63.3% | 97.5% | +0.17 |

n = pairs both graded (batch-00 imported 2026-11-27, so all three judges cover the 120).
3-judge majority (median of three) on 120 pairs: 60 unanimous, 55 two agree, 5 all differ.

What they disagree about: almost every disagreement is one grade apart (97-99% within
one). Groq grades higher than Gemini in 31 of 39 disagreements. Tagged from the lower
grader's reason, 24 disagreements involve seniority, 19 a dealbreaker such as salary and
19 location (a disagreement can carry several).
Gemini rates AI-training gigs 0 where Groq gives 2 (5 cases). Gemini and Cowork
disagree in both directions about equally.

Agreement between LLM judges shows how stable the labels are. It does not show agreement with people.

## 6. Results (placeholders)

All LLM-judged (Gemini), mean over 25 profiles, 95% bootstrap CI over profiles.

| Variant (query mode) | NDCG@10 | MRR | Recall@30 | judged@10 |
|---|---|---|---|---|
| keyword | {ndcg_bm25} | {mrr_bm25} | {r30_bm25} | {j_bm25} |
| vector | {ndcg_vector} | … | … | … |
| hybrid | {ndcg_fused} | … | … | … |
| +personalisation | {ndcg_rescore} | … | … | … |
| +rerank 10@128 | {ndcg_r10} | … | … | … |
| +rerank 20@128 | {ndcg_r20} | … | … | … |
| +rerank 30@256 | {ndcg_r30} | … | … | … |

Paired comparisons (difference, CI, permutation p): {comparisons_table}

Profile mode, and query+profile vs profile only: {profile_mode_table}

## 7. Robustness

Each main comparison recomputed under Gemini (all pairs and blind only), Groq, Cowork and
the 3-judge majority (blind pairs, condensed), and Cowork on all pooled pairs once its
batches are in (pending batches 00-04). For each: holds, weaker, differs or reverses.
{robustness_table}

## 7a. Read-only checks for this report (2026-11-27)

**Stale postings** (`posted_at` before the snapshot date minus 90 or 365 days):

| Source | searchable jobs | > 90 days | > 365 days | eval pairs | > 90 days | > 365 days |
|---|---:|---:|---:|---:|---:|---:|
| adzuna | 1,470 | 938 (63.8%) | 755 (51.4%) | 145 | 93 (64%) | 64 (44%) |
| ashby | 4,758 | 939 (19.7%) | 101 (2.1%) | 113 | 28 (25%) | 7 (6%) |
| greenhouse | 9,906 | 3,922 (39.6%) | 1,289 (13.0%) | 139 | 64 (46%) | 29 (21%) |
| himalayas | 6,727 | 1 (0.0%) | 0 | 566 | 0 | 0 |
| lever | 734 | 396 (54.0%) | 184 (25.1%) | 26 | 12 (46%) | 3 (12%) |
| remotive | 15 | 0 | 0 | 8 | 0 | 0 |
| smartrecruiters | 95 | 24 (25.3%) | 13 (13.7%) | 3 | 0 | 0 |
| all | 23,705 | 6,220 (26.2%) | 2,342 (9.9%) | 1,000 | 197 (20%) | 103 (10%) |

Himalayas looks fresh partly because of how it dates postings. An old `posted_at` on an
ATS board can be an evergreen or re-opened requisition, not necessarily a dead job.

**Coinbase #13 duplicate** (`72deffe2…` kept, `e413f65b…` merged into it,
`near_duplicate_text`, score 0.976): 37 of 38 sentences identical. The one difference is
the pay range top ($197,010 vs $218,900; postings of 2026-07-31 and 2026-11-16). The kept
job has `openings_count` 2 and keeps the older posting's salary (max $197,010). The
newer, higher range survives only on the merged-away row. Neither job is in any eval
ranking. Full diff: `eval/review/coinbase-13-diff.md` (gitignored, quotes the posting).

**Pending tag fixes.** Every fix from the owner's second tag review was applied before
the snapshot: `retag --dry-run` on the snapshot database changes 0 of 26,108 rows, so 0
of the 1,000 pairs change tags. The open recheck sheet (`eval/review/tags-recheck.md`,
20 jobs, verdicts pending) touches 5 pairs (job `5fd077e6…`, contract, in p01, p03, p06
and p17; job `62502784…`, staffing agency, in p14). That is the most any verdict on that
sheet could change.

## 8. ADR 0003: the interactive rerank setting

Rule (paired form, owner decision 2026-11-27): among no-rerank, 10@128, 20@128 and
30@256 in query mode, a setting is eligible if it is within 0.01 NDCG@10 of the best, or if the
paired CI of its difference to the best includes 0. Choose the eligible setting with the
lowest single-search p95 (docs/bench/search-2026-11-24.md: 75 / 331 / 593 / 1,817 ms).
Decision: {rerank_choice}; meets 300 ms: {meets_300}.

## 9. CI regression gate

`make eval` (CI: a step in the `docker` job) loads the committed reduced corpus
(`eval/snapshots/2026-11-25/reduced/`, 17.1 MB: the 1,014 jobs any variant ranked plus
3,000 source-proportional distractors, sha256 manifest). It builds BM25, runs the
query-mode variants with the real models, and fails if any mean NDCG@10 drops more than
0.02 below `eval/gate/baseline.json`. It takes about 45 s locally and gives the same
numbers on every run. The step is non-blocking until the baseline is re-measured on the
final labels.

## 10. Limitations

- **No human relevance labels.** Every grade comes from an LLM. Gemini is the single
  primary judge, and Groq and Claude Cowork are LLMs too. They share one rubric and
  may share biases, so their agreement with each other does not stand in for agreement
  with people.
- **Single primary judge.** Every headline number depends on Gemini's labels. Section 7
  shows which conclusions survive under the other judges. Those checks use only the 120
  blind pairs (about 5 per profile) until Cowork grades the rest.
- **Pool bias.** The judged set is what these 14 variants surfaced in their top 10 (plus
  20-per-profile pooling below that). A system that finds good jobs none of them ranked
  would get no credit. Recall@30 counts only judged relevant jobs.
- **Judges read a shortened posting.** The judge input is the structured fields plus
  the first ~1,400 characters of the description (owner decision 2026-11-26, input v2).
  Of the 1,000 pairs, 764 (76%) are cut, dropping a median 1,728 characters. In 323
  (32%) the first years-of-experience statement, and in 255 (26%) the
  requirements/qualifications heading, lies after the cut. The sheets Cowork grades
  carry exactly the same text (verified for all 1,000 pairs), so the judges are
  compared on equal input. Separately, 145 pairs (130 Adzuna jobs) are source
  snippets of about 500 characters: the API returns no more.
- 25 fictional profiles, so the CIs cover these profiles only. There is one snapshot.
- Latency is from the 2026-11-24 benchmark on an 11,531-job pool, not the snapshot.
- Not done (deferred by the owner): warm vs cold personalisation, the source_quality
  and gig/agency down-rank ablations, and the int8 / TinyBERT rerank rows.
