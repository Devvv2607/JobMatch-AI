# JobMatch AI: how good is the search? (Phase 4 evaluation, eval-2026-11-25)

**Every relevance number in this report is LLM-judged (Gemini). There are no human
relevance labels.** The text is written by hand; the blocks marked `BEGIN`/`END` are
filled by `make eval-final` from the generated report
(`eval/reports/<date>-<commit>.md` and `.json`), so a number here always matches a file
and a command.

<!-- BEGIN:status -->
_Status: numbers pending: the final run has not been made yet._
<!-- END:status -->

## 1. The question

JobMatch ranks job postings for a job seeker. Each stage of its search pipeline costs
something: latency, CPU, complexity. This evaluation asks what each stage buys in
ranking quality, measured the same way for all of them:

| Step | Variant | What it adds |
|---|---|---|
| keyword | `bm25` | BM25 over title, skills, locations and the stripped description |
| vector | `vector` | cosine search over one embedding per job (pgvector HNSW) |
| hybrid | `fused` | reciprocal-rank fusion of the two (k = 60) |
| +personalisation | `rescore` | the personalised re-score of the fused candidates |
| +rerank N@T | `rerank_N_T` | a cross-encoder on the re-scored top N, T tokens a pair (10@128, 20@128, 30@256) |

Each variant runs in two modes: `query` (the person typed a search; their profile is
used too), which is what interactive search does, and `profile` (no typed search), which
is what the daily digest does.

<!-- BEGIN:key-results -->
_Key results: filled by the final run._
<!-- END:key-results -->

## 2. The evaluation design

**A frozen job pool.** The live pool changes every day, so every number comes from one
snapshot taken on 2026-11-25: a database backup restored into its own database, with
the keyword index frozen beside it (`eval/snapshots/2026-11-25/manifest.json`, 23,705
searchable jobs). Every ranking can be rebuilt exactly from it.

**Twenty-five fictional job seekers.** No real person's data is used. The profiles
(`eval/profiles/`) are about 70% India-based (freshers, 1-3 and 3-6 years) across ML/AI,
data, backend, full-stack and product/analyst work, and the rest are US/EU or
remote-seeking. Each has skills, preferences, dealbreakers and a short typed search,
written so that some jobs clearly fit and many clearly do not.

**Which jobs get judged: pooling, then a depth-10 fill.** Judging every job for every
person is impossible, so the evaluation judges what the systems actually show.
1. Every variant ranked its top 30 for every profile (`runs.jsonl`).
2. *Pool:* for each profile, 20 jobs from the union of the variants' top 10s, best rank
   first, capped so that no source, gig work or staffing agencies could dominate:
   500 pairs.
3. *The gap we found:* the top-10 union holds 25-49 jobs per profile, so the pool left
   about a third of each variant's top 10 unjudged. Counting those as irrelevant would
   have penalised variants unevenly.
4. *The fix:* every job any variant ranked in its top 10 was added and judged (500 more
   pairs, `strata.pool = "fill-depth10"`). Now every variant's top 10 is fully judged,
   so NDCG@10 needs no assumption about unjudged jobs.

**The blind set.** 120 of the pooled pairs, stratified and fixed before any judge ran,
are the common ground on which the judges are compared.

## 3. The judges: why LLMs, and why three

Judging 1,000 (person, job) pairs by hand takes days. The owner decided not to label,
so every grade comes from a language model following one written rubric
(`backend/app/prompts/eval_judge/v1.md`): **3** apply today, **2** good with gaps,
**1** same field but wrong fit, **0** irrelevant. A broken dealbreaker caps the grade at
1, and when a dealbreaker can't be checked from the posting the grade leans to 2.

One LLM's grades are only as good as that model. So three judges from three different
model families grade the blind set:

| Judge | Family | Role | Pairs |
|---|---|---|---:|
| Gemini `gemini-3.5-flash-lite` | Google | **primary**: every reported metric | 1,000 |
| Groq `openai/gpt-oss-120b` | OpenAI open-weight | second opinion | 120 blind |
| Claude Cowork (an AI agent) | Anthropic | third opinion | 120 blind |

If the conclusions hold under all three, and under their majority, they are not
artefacts of one model's taste. All three read exactly the same input for each pair:
every grade stores a sha256 of the text the judge saw, and only grades with matching
hashes are compared. Agreement between LLMs shows how stable the labels are. It is not
agreement with people.

## 4. The truncation story

**The finding.** To keep each call cheap, the first judge input (v2) sent each posting's
structured fields plus only its first ~1,400 characters. Postings put the requirements
near the end, so 764 of the 1,000 pairs were cut, and in about a third of them the
years-of-experience requirement was cut off. A judge that never sees "5+ years" can't
mark a role too senior.

**The controlled check.** Instead of guessing, we tested it. A new input (v3) trims by
section rather than by position: requirements and any experience or seniority statement
first, then responsibilities, then the rest, with company intro, benefits and
equal-opportunity text dropped first, within 3,200 characters. For short postings v3
sends exactly the same text as v2 (same sha256). Gemini then re-judged, on v3, the 30
blind pairs whose experience statement v2 had cut, plus a control of 29 blind pairs that
were never cut.

**The noise checks.** A difference only means something if the judge is consistent.
The control (identical input, judged again) changed 0 of 29 grades, and a second v3 run
of 20 long, cut postings changed 0 of 20. So run-to-run noise is near zero, and any change
on the cut pairs comes from the text the judge could see.

<!-- BEGIN:input-fix -->
_Input-fix numbers: filled by the final run._
<!-- END:input-fix -->

**The decision and the re-judge.** The effect cleared the pre-set bar (at least 10
percentage points, or at least 3 changes over experience or seniority), so every cut
pair was re-judged on v3 by Gemini, the cut blind pairs by Groq, and the blind pairs by
Claude Cowork on the same v3 text. Uncut pairs keep their grades: their input did not
change. The v2 grades are kept as the baseline, and the main metrics are shown under
both (section 6).

**One example: `p20:7377a6a8`** (Cloudflare, Data Engineer, Austin; the candidate is a
data analyst with 2 years of SQL, dbt and Tableau). On v2 the requirements were cut, and
both Gemini and Claude Cowork graded it 2. Gemini called it "a step away from the
candidate's analytics background", and Cowork flagged only the unstated salary. On v3
both independently moved it to 1. Gemini: "a senior-level data engineering position
requiring 5+ years of experience and core backend languages like Go or Scala". Cowork:
"core work is building pipelines and data services in Go and Scala… Candidate is a
2-year SQL/dbt/Tableau analyst".

## 5. Do the judges agree?

<!-- BEGIN:agreement -->
_Agreement tables: filled by the final run (before vs after the input fix on identical
pairs, with a paired bootstrap of the change)._
<!-- END:agreement -->

## 6. Results

<!-- BEGIN:labels -->
_Label counts: filled by the final run._
<!-- END:labels -->

<!-- BEGIN:metrics -->
_Per-variant metrics with bootstrap CIs: filled by the final run._
<!-- END:metrics -->

<!-- BEGIN:comparisons -->
_Paired comparisons: filled by the final run._
<!-- END:comparisons -->

<!-- BEGIN:subsets -->
_All pairs / without source snippets / posted within 90 days: filled by the final run._
<!-- END:subsets -->

<!-- BEGIN:sensitivity -->
_Final labels vs v2 labels: filled by the final run._
<!-- END:sensitivity -->

## 7. Do the conclusions hold under every judge?

<!-- BEGIN:robustness -->
_Robustness table: filled by the final run._
<!-- END:robustness -->

## 8. Which rerank setting for interactive search (ADR 0003)

<!-- BEGIN:adr -->
_ADR 0003 decision: filled by the final run._
<!-- END:adr -->

The rule and its reasoning are in `docs/decisions/0003-rerank-profiles.md`.

## 9. Checks made along the way (2026-11-27, read-only)

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

An old `posted_at` on an ATS board can be an evergreen or re-opened requisition, not
necessarily a dead job. A freshness signal is backlogged for Phase 5, and section 6
shows the main numbers on postings within 90 days.

**Source snippets.** 145 pairs (130 Adzuna jobs) carry a ~500-character snippet: the
source API returns no more. Every judge saw the same snippet. Section 6 shows the main
numbers without them.

**A duplicate that keeps the older pay range** (Coinbase #13, `72deffe2…` kept,
`e413f65b…` merged in): 37 of 38 sentences are identical, and only the top of the pay
range differs ($197,010 vs $218,900). The kept job carries the older range. Neither job
is in any eval ranking. Making dedup keep the newest posting is backlogged, with a dry
run first.

**Tag fixes.** Every fix from the owner's tag review was in before the snapshot: a
dry-run retag of the snapshot changes 0 of 26,108 rows, so 0 eval pairs change.

## 10. The CI regression gate

`make eval` (a step in CI's `docker` job) loads a committed reduced corpus
(`eval/snapshots/2026-11-25/reduced/`, 17.1 MB: the 1,014 jobs any variant ranked plus
3,000 distractors, with a sha256 manifest). It builds the keyword index, runs the
query-mode variants with the real models, and fails if any mean NDCG@10 drops more than
0.02 below `eval/gate/baseline.json`. It takes about 45 seconds and gives the same
numbers on every run. Its baseline is re-measured on the final labels.

## 11. Limitations

- **No human relevance labels.** Every grade comes from an LLM. The three judges share
  one rubric and may share blind spots, so their agreement with each other is not
  agreement with job seekers.
- **One primary judge.** Every headline number uses Gemini's labels. Section 7 shows
  which conclusions survive under Groq, Claude Cowork and their majority. Those checks
  use the 120 blind pairs (about 5 per profile), so they are much noisier than the main
  numbers.
- **Pool bias.** Only what these 14 variants ranked in their top 10 is fully judged. A
  new system that finds good jobs none of them ranked would get no credit, and recall
  counts only judged relevant jobs (Recall@30: the API returns 30).
- **Shortened postings.** Even input v3 is capped at 3,200 characters, and 145 pairs
  are source snippets. Every judge saw the same text, so comparisons are fair, but a
  requirement that sits beyond the cap is invisible to all of them.
- **Small and synthetic.** 25 fictional profiles and one snapshot. The confidence
  intervals describe these profiles, not every kind of job seeker.
- **Latency** comes from the 2026-11-24 benchmark on an 11,531-job pool on one laptop,
  not from the snapshot.
- **Not done** (deferred by the owner): warm vs cold personalisation, the source-quality
  and gig/agency down-rank ablations, and the int8 / TinyBERT rerank rows.
