# JobMatch AI: how good is the search? (Phase 4 evaluation, eval-2026-11-25)

**Every relevance number in this report is LLM-judged (Gemini). There are no human
relevance labels.** The text is written by hand; the blocks marked `BEGIN`/`END` are
filled by `make eval-final` from the generated report
(`eval/reports/<date>-<commit>.md` and `.json`), so a number here always matches a file
and a command.

<!-- BEGIN:status -->
_Final run 2026-11-28T10:00:28+00:00, commit 65efa6a: `eval/reports/2026-11-28-65efa6a.md`._
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
### Key results (query mode, LLM-judged (Gemini))

- `bm25` (keyword): NDCG@10 0.462 [0.381, 0.549]
- `fused` (hybrid): NDCG@10 0.556 [0.486, 0.631]
- `rescore` (+personalisation): NDCG@10 0.516 [0.446, 0.586]
- `rerank_10_128` (+rerank 10@128): NDCG@10 0.575 [0.508, 0.646]
- hybrid vs keyword: +0.094 [+0.047, +0.144], p=0.001 (better)
- +personalisation vs hybrid: -0.040 [-0.100, +0.013], p=0.194 (no clear difference)
- +rerank 10@128 vs +personalisation: +0.059 [+0.008, +0.114], p=0.049 (better)
- +rerank 10@128 vs keyword: +0.112 [+0.053, +0.172], p=0.002 (better)
- Blind pairs, gemini vs groq: weighted kappa 0.73 (n=120)
- Blind pairs, gemini vs cowork: weighted kappa 0.79 (n=120)
- Blind pairs, groq vs cowork: weighted kappa 0.72 (n=120)
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
### The input fix (judge input v2 -> v3)

Input v2 sent each description's first ~1,400 characters; 764 of 1000 pairs were cut, often before the experience requirement. Input v3 trims by section (requirements and experience/seniority first, boilerplate last, cap 3,200 characters) and is identical to v2 for every uncut pair (same sha256).

- Controlled check (Gemini, same settings, cache off): cut pairs 8/30 grades changed (26.7%; 6 down, 2 up), control 0/29 (0.0%): effect +26.7 points.
- Long-text noise: 0 of 20 cut pairs changed grade when Gemini judged the same v3 input a second time.
- All cut pairs re-judged (764 of 764): 143 changed (18.7%; 91 down, 52 up); transitions {'2->1': 49, '2->3': 16, '3->2': 24, '1->0': 11, '1->2': 23, '3->1': 7, '0->1': 13}.
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
### Agreement between the LLM judges

After the input fix (final labels). On the blind pairs a grade is used only if its judge input has the same sha256 as Gemini's final input for that pair: gemini 120 of 120, groq 120 of 120, cowork 120 of 120.

#### Blind pairs (120 pairs; graded {'gemini': 120, 'groq': 120, 'cowork': 120})

n is the number of pairs both judges graded.

| Judges | n | weighted kappa [95% CI] | exact | within one | mean a - b |
|---|---:|---|---:|---:|---:|
| gemini vs groq | 120 | 0.725 [0.615, 0.810] | 70.0% | 98.3% | -0.15 |
| gemini vs cowork | 120 | 0.788 [0.704, 0.854] | 75.0% | 100.0% | -0.02 |
| groq vs cowork | 120 | 0.723 [0.603, 0.813] | 69.2% | 97.5% | +0.13 |

##### gemini vs groq

Confusion (rows gemini, columns groq):

| | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| **0** | 4 | 1 | 2 | 0 |
| **1** | 4 | 39 | 10 | 0 |
| **2** | 0 | 5 | 32 | 13 |
| **3** | 0 | 0 | 1 | 9 |

Most common disagreements (gemini/groq): 2/3 x13, 1/2 x10, 2/1 x5, 1/0 x4, 0/2 x2.

Themes, tagged from the lower grader's reason and the posting's facts (a disagreement can carry several or none):

- **dealbreakers**: 11 (31%); gemini higher 1, groq higher 10
  - `p19:82c9cbe4-cc26-4720-aa48-cd62e189aa6c`: gemini 0, groq 2; gemini (lower): "This is a per-task AI training/freelance gig rather than a traditional engineering role, violating the candidate's search for a full-time senior/staff position. Additionally, no salary is stated."
  - `p01:56e041b1-c85e-4c85-8148-4069d52c2103`: gemini 1, groq 2; gemini (lower): "The candidate seeks a junior or intern ML role, but this posting for a Machine Learning Engineer does not specify a junior level or experience requirement, and lacks salary and workplace details."
  - `p03:363b0a55-125a-428b-995b-a4624a421f1a`: gemini 1, groq 0; groq (lower): "The role is a Data Engineer position, not a senior ML engineer/recommendations role the candidate seeks, and it is in-office with no salary disclosed, violating location/remote preference and salary dealbreaker."
- **seniority**: 25 (69%); gemini higher 7, groq higher 18
  - `p09:3fcfaa34-664e-4c37-b15a-e3443bed4014`: gemini 0, groq 2; gemini (lower): "The candidate seeks a permanent senior backend engineering role in payments, whereas this is a freelance gig for training AI coding agents. Per-task AI training/rating gigs are a different kind of work."
  - `p19:82c9cbe4-cc26-4720-aa48-cd62e189aa6c`: gemini 0, groq 2; gemini (lower): "This is a per-task AI training/freelance gig rather than a traditional engineering role, violating the candidate's search for a full-time senior/staff position. Additionally, no salary is stated."
  - `p01:02be8406-2647-40ab-baea-80a12d49e96b`: gemini 1, groq 2; gemini (lower): "The role requires solid, hands-on production experience building recommendation systems and acting as the first data scientist, which is too senior for a final-year student with only academic projects and no industry experience."
- **location**: 18 (50%); gemini higher 7, groq higher 11
  - `p03:363b0a55-125a-428b-995b-a4624a421f1a`: gemini 1, groq 0; groq (lower): "The role is a Data Engineer position, not a senior ML engineer/recommendations role the candidate seeks, and it is in-office with no salary disclosed, violating location/remote preference and salary dealbreaker."
  - `p04:35c49b2a-c9e8-4c1f-952b-b6c3aaac81a5`: gemini 2, groq 3; gemini (lower): "The role is an entry-level Business Analyst position in India matching the candidate's fresher level and field, but it requires being based in Bangalore while the candidate lives in Chennai."
  - `p04:e22d1c40-07a7-4355-8517-58a170593053`: gemini 2, groq 3; gemini (lower): "The role is a remote internship in India matching the candidate's fresher level and location, but it focuses heavily on data scraping, lead generation, and research rather than core statistical data analysis."
- **gigs**: 5 (14%); gemini higher 1, groq higher 4
  - `p09:3fcfaa34-664e-4c37-b15a-e3443bed4014`: gemini 0, groq 2; gemini (lower): "The candidate seeks a permanent senior backend engineering role in payments, whereas this is a freelance gig for training AI coding agents. Per-task AI training/rating gigs are a different kind of work."
  - `p19:82c9cbe4-cc26-4720-aa48-cd62e189aa6c`: gemini 0, groq 2; gemini (lower): "This is a per-task AI training/freelance gig rather than a traditional engineering role, violating the candidate's search for a full-time senior/staff position. Additionally, no salary is stated."
  - `p06:da0d9dec-faef-4d80-b804-bbca1d13a644`: gemini 2, groq 3; gemini (lower): "The role matches the senior level, experimentation focus, and India eligibility. However, it is an employment contract rather than permanent employment, and no salary is stated."
- **none of these**: 3 (8%); gemini higher 1, groq higher 2
  - `p16:7d8137c9-231f-4c77-b463-79a5bbc2d7c7`: gemini 2, groq 1; groq (lower): "Field matches (GenAI/LLM), but requires 3 years experience vs candidate’s 1.5 years and workplace is unknown, while candidate needs remote work."
  - `p22:ab42d5a2-30be-488e-9a43-c3a355a0d006`: gemini 1, groq 2; gemini (lower): "This is a Developer Relations role rather than a standard full-stack engineering position, shifting the core responsibilities away from software development toward content creation and public advocacy."
  - `p24:18c16f2f-45a7-4ebb-b9d3-13bfcab7e62e`: gemini 0, groq 1; gemini (lower): "This is a backend development role requiring C# and C++, which is a completely different field and tech stack from the candidate's MLOps and Python expertise."
- **all disagreements**: 36 (100%); gemini higher 10, groq higher 26

##### gemini vs cowork

Confusion (rows gemini, columns cowork):

| | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| **0** | 5 | 2 | 0 | 0 |
| **1** | 2 | 45 | 6 | 0 |
| **2** | 0 | 11 | 31 | 8 |
| **3** | 0 | 0 | 1 | 9 |

Most common disagreements (gemini/cowork): 2/1 x11, 2/3 x8, 1/2 x6, 1/0 x2, 0/1 x2.

Themes, tagged from the lower grader's reason and the posting's facts (a disagreement can carry several or none):

- **dealbreakers**: 10 (33%); gemini higher 3, cowork higher 7
  - `p01:56e041b1-c85e-4c85-8148-4069d52c2103`: gemini 1, cowork 2; gemini (lower): "The candidate seeks a junior or intern ML role, but this posting for a Machine Learning Engineer does not specify a junior level or experience requirement, and lacks salary and workplace details."
  - `p04:e22d1c40-07a7-4355-8517-58a170593053`: gemini 2, cowork 1; cowork (lower): "Related but wrong fit: an internship scraping and verifying sales leads for printing businesses, more data-entry research than analytics. Remote internship open to India fits the dealbreakers."
  - `p09:b548d52c-ff57-40c0-81d3-cea73dda20d9`: gemini 2, cowork 1; cowork (lower): "Cannot work it from where they are: onsite at Delhi HQ while the candidate lives in Bengaluru, and services are Python rather than Java/Kotlin. Salary not stated."
- **seniority**: 18 (60%); gemini higher 7, cowork higher 11
  - `p01:56e041b1-c85e-4c85-8148-4069d52c2103`: gemini 1, cowork 2; gemini (lower): "The candidate seeks a junior or intern ML role, but this posting for a Machine Learning Engineer does not specify a junior level or experience requirement, and lacks salary and workplace details."
  - `p01:7d449902-5069-414d-8a0b-618f54786b75`: gemini 1, cowork 2; gemini (lower): "The role asks for an experienced machine learning engineer, while the candidate is a fresh graduate looking for a junior or intern position, representing a clear level mismatch."
  - `p04:35c49b2a-c9e8-4c1f-952b-b6c3aaac81a5`: gemini 2, cowork 3; gemini (lower): "The role is an entry-level Business Analyst position in India matching the candidate's fresher level and field, but it requires being based in Bangalore while the candidate lives in Chennai."
- **location**: 14 (47%); gemini higher 8, cowork higher 6
  - `p04:35c49b2a-c9e8-4c1f-952b-b6c3aaac81a5`: gemini 2, cowork 3; gemini (lower): "The role is an entry-level Business Analyst position in India matching the candidate's fresher level and field, but it requires being based in Bangalore while the candidate lives in Chennai."
  - `p06:44abece8-d223-4af4-9780-26cc63234055`: gemini 2, cowork 1; cowork (lower): "Level and skills mismatch: Staff Data Scientist leading senior DS/MLEs across recommendations, search, ads and LLM/agent systems; candidate is a 5-year senior DS focused on experimentation and churn models. Bengaluru hybrid and India eligib"
  - `p09:2d1573a9-5f47-4470-93ed-33eec5a60952`: gemini 2, cowork 1; cowork (lower): "Cannot work it from where they are: candidates must be based in Gurgaon for hybrid work, while the candidate is in Bengaluru; also asks 6+ years against 5. Java, Kafka and PostgreSQL fit."
- **gigs**: 3 (10%); gemini higher 1, cowork higher 2
  - `p11:3e4bcc3e-13cc-43ed-9614-18018370857c`: gemini 2, cowork 3; gemini (lower): "The role matches the candidate's exact tech stack (Next.js, React, NestJS, PostgreSQL) and seniority, and allows remote work from India. However, it is a freelance/contract gig (1099/corp-to-corp) rather than a permanent role, which may not"
  - `p22:24d407e2-f819-40e2-b917-6f8fc5e4dfd3`: gemini 3, cowork 2; cowork (lower): "Real gap: full-stack React/TypeScript/GraphQL/Node/PostgreSQL role matching the stack, open worldwide, but fully remote while the candidate prefers hybrid or on-site; posted by a staffing agency; level not stated."
  - `p23:223fbb67-f281-431d-a214-fb79ff00ff36`: gemini 0, cowork 1; gemini (lower): "The candidate is a product manager looking for SaaS product roles, while the job posting is for a technical Data Scientist position focused on machine learning and modeling."
- **none of these**: 4 (13%); gemini higher 3, cowork higher 1
  - `p15:f9957ff3-16d9-4390-9eec-4720e0c23efe`: gemini 1, cowork 0; cowork (lower): "Different kind of work: business development and partnerships manager driving trading volume and partner deals, not product management with roadmap ownership."
  - `p23:2cfe34d7-69d3-4e3a-a7a7-4503f943b679`: gemini 1, cowork 0; cowork (lower): "Different kind of work: Customer Success Manager (account management, renewals, upsells), not product management."
  - `p24:18c16f2f-45a7-4ebb-b9d3-13bfcab7e62e`: gemini 0, cowork 1; gemini (lower): "This is a backend development role requiring C# and C++, which is a completely different field and tech stack from the candidate's MLOps and Python expertise."
- **all disagreements**: 30 (100%); gemini higher 14, cowork higher 16

##### groq vs cowork

Confusion (rows groq, columns cowork):

| | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| **0** | 4 | 4 | 0 | 0 |
| **1** | 1 | 37 | 7 | 0 |
| **2** | 2 | 16 | 26 | 1 |
| **3** | 0 | 1 | 5 | 16 |

Most common disagreements (groq/cowork): 2/1 x16, 1/2 x7, 3/2 x5, 0/1 x4, 2/0 x2.

Themes, tagged from the lower grader's reason and the posting's facts (a disagreement can carry several or none):

- **dealbreakers**: 5 (14%); groq higher 4, cowork higher 1
  - `p04:e22d1c40-07a7-4355-8517-58a170593053`: groq 3, cowork 1; cowork (lower): "Related but wrong fit: an internship scraping and verifying sales leads for printing businesses, more data-entry research than analytics. Remote internship open to India fits the dealbreakers."
  - `p03:363b0a55-125a-428b-995b-a4624a421f1a`: groq 0, cowork 1; groq (lower): "The role is a Data Engineer position, not a senior ML engineer/recommendations role the candidate seeks, and it is in-office with no salary disclosed, violating location/remote preference and salary dealbreaker."
  - `p06:da0d9dec-faef-4d80-b804-bbca1d13a644`: groq 3, cowork 2; cowork (lower): "Real gap: senior data scientist on churn, LTV and multivariate testing, remote and open to India, a strong match, but it is a contract engagement (close to the no-freelance dealbreaker) and leans heavily on pipeline engineering."
- **seniority**: 23 (62%); groq higher 13, cowork higher 10
  - `p01:02be8406-2647-40ab-baea-80a12d49e96b`: groq 2, cowork 1; cowork (lower): "Level clearly wrong: first and sole data scientist building production recommendation systems, requiring solid hands-on production recsys experience; candidate is a fresher with coursework only. Remote India otherwise fits."
  - `p01:7d449902-5069-414d-8a0b-618f54786b75`: groq 1, cowork 2; groq (lower): "The role is a full-time Machine Learning Engineer requiring experience, while the candidate is a fresh graduate with no industry experience; seniority mismatch outweighs eligibility and field match."
  - `p03:363b0a55-125a-428b-995b-a4624a421f1a`: groq 0, cowork 1; groq (lower): "The role is a Data Engineer position, not a senior ML engineer/recommendations role the candidate seeks, and it is in-office with no salary disclosed, violating location/remote preference and salary dealbreaker."
- **location**: 14 (38%); groq higher 7, cowork higher 7
  - `p01:7d449902-5069-414d-8a0b-618f54786b75`: groq 1, cowork 2; groq (lower): "The role is a full-time Machine Learning Engineer requiring experience, while the candidate is a fresh graduate with no industry experience; seniority mismatch outweighs eligibility and field match."
  - `p03:363b0a55-125a-428b-995b-a4624a421f1a`: groq 0, cowork 1; groq (lower): "The role is a Data Engineer position, not a senior ML engineer/recommendations role the candidate seeks, and it is in-office with no salary disclosed, violating location/remote preference and salary dealbreaker."
  - `p06:44abece8-d223-4af4-9780-26cc63234055`: groq 2, cowork 1; cowork (lower): "Level and skills mismatch: Staff Data Scientist leading senior DS/MLEs across recommendations, search, ads and LLM/agent systems; candidate is a 5-year senior DS focused on experimentation and churn models. Bengaluru hybrid and India eligib"
- **gigs**: 4 (11%); groq higher 3, cowork higher 1
  - `p09:3fcfaa34-664e-4c37-b15a-e3443bed4014`: groq 2, cowork 0; cowork (lower): "Different kind of work: paid per accepted task to evaluate AI coding-agent output, an AI-training gig, not a backend engineering job."
  - `p19:82c9cbe4-cc26-4720-aa48-cd62e189aa6c`: groq 2, cowork 0; cowork (lower): "Different kind of work: per-task AI-training project (creating and validating ML tasks), freelance gig with flexible hours, not an ML engineering job."
  - `p06:da0d9dec-faef-4d80-b804-bbca1d13a644`: groq 3, cowork 2; cowork (lower): "Real gap: senior data scientist on churn, LTV and multivariate testing, remote and open to India, a strong match, but it is a contract engagement (close to the no-freelance dealbreaker) and leans heavily on pipeline engineering."
- **none of these**: 4 (11%); groq higher 4, cowork higher 0
  - `p08:e1cc6af0-bea8-458e-bff3-d22ad01636b9`: groq 2, cowork 1; cowork (lower): "Related but most required skills missing: DevOps role running bare-metal and AWS Kubernetes, Helm, CSI storage, CloudNativePG backups, Terraform and Argo CD; candidate is a 2-year Go backend developer. Remote India fits."
  - `p15:f9957ff3-16d9-4390-9eec-4720e0c23efe`: groq 1, cowork 0; cowork (lower): "Different kind of work: business development and partnerships manager driving trading volume and partner deals, not product management with roadmap ownership."
  - `p18:c178a580-2c6c-4d43-a353-ae17bd1ceab1`: groq 2, cowork 1; cowork (lower): "Most required skills missing: role is ML compiler work (MLIR lowering, kernels, accelerator bring-up), not computer vision. Candidate's CV and CUDA inference experience only partly overlaps. Bengaluru hybrid fits."
- **all disagreements**: 37 (100%); groq higher 25, cowork higher 12

3-judge majority (median of three): {'unanimous': 69, 'two_agree': 50, 'all_differ': 1, 'pairs': 120}

#### Before vs after the input fix, on identical pairs

Both columns use the same 120 blind pairs (those where every judge has a final grade from hash-identical input); 'before' uses each judge's v2-era grade for those pairs (Claude Cowork's mostly from the labelling tool).

| Judges | n | weighted kappa [95% CI], before | after | change (after - before) [95% paired bootstrap CI] | verdict |
|---|---:|---|---|---|---|
| gemini vs groq | 120 | 0.697 [0.585, 0.788] | 0.725 [0.615, 0.810] | +0.028 [-0.051, +0.114] (n=120) | no clear change |
| gemini vs cowork | 120 | 0.658 [0.550, 0.746] | 0.788 [0.704, 0.854] | +0.130 [+0.034, +0.230] (n=120) | improved |
| groq vs cowork | 120 | 0.677 [0.559, 0.769] | 0.723 [0.603, 0.813] | +0.046 [-0.065, +0.156] (n=120) | no clear change |

The change is a paired bootstrap over the same pairs (2,000 resamples): agreement is said to have improved only for a judge pair whose CI excludes 0.
<!-- END:agreement -->

## 6. Results

<!-- BEGIN:labels -->
### Labels

1000 (profile, job) pairs: 500 pooled, plus 500 added by `fill-depth10`. The blind set is 120 of the pooled pairs.

| Judge | Pairs graded | label_source | Grades 0 / 1 / 2 / 3 |
|---|---:|---|---|
| Gemini (gemini-3.5-flash-lite) | 1000 | llm | 121 / 461 / 354 / 64 |
| Groq (openai/gpt-oss-120b) | 120 | llm | 8 / 45 / 45 / 22 |
| Claude Cowork (AI agent) | 121 | llm | 7 / 58 / 39 / 17 |

Primary labels: Gemini. No pair has a human label.

Labels used: final: judge input v3 (section-aware) for the pairs whose description v2 cut, the existing labels for every other pair (identical input, same sha256). Claude Cowork is a third judge on the 120 blind pairs only (its other batches were cancelled, owner decision 2026-11-27).
<!-- END:labels -->

<!-- BEGIN:metrics -->
### Metrics, LLM-judged (Gemini), primary

Mean over 25 profiles, 95% percentile bootstrap CI over profiles. judged@10 is the share of a variant's top 10 that Gemini graded.

| Variant | NDCG@10 | MRR | Recall@30 | judged@10 |
|---|---|---|---|---|
| `profile:bm25` | 0.503 [0.423, 0.589] | 0.663 [0.530, 0.798] | 0.520 [0.437, 0.603] | 1.00 |
| `profile:fused` | 0.505 [0.425, 0.591] | 0.630 [0.469, 0.785] | 0.549 [0.475, 0.625] | 1.00 |
| `profile:rerank_10_128` | 0.524 [0.442, 0.612] | 0.676 [0.523, 0.823] | 0.549 [0.475, 0.625] | 1.00 |
| `profile:rerank_20_128` | 0.535 [0.456, 0.619] | 0.745 [0.589, 0.888] | 0.549 [0.475, 0.625] | 1.00 |
| `profile:rerank_30_256` | 0.548 [0.471, 0.630] | 0.735 [0.595, 0.864] | 0.549 [0.475, 0.625] | 1.00 |
| `profile:rescore` | 0.546 [0.480, 0.617] | 0.682 [0.558, 0.805] | 0.549 [0.475, 0.625] | 1.00 |
| `profile:vector` | 0.508 [0.434, 0.587] | 0.625 [0.474, 0.772] | 0.523 [0.440, 0.607] | 1.00 |
| `query:bm25` | 0.462 [0.381, 0.549] | 0.558 [0.420, 0.705] | 0.596 [0.509, 0.676] | 1.00 |
| `query:fused` | 0.556 [0.486, 0.631] | 0.743 [0.601, 0.875] | 0.666 [0.608, 0.725] | 1.00 |
| `query:rerank_10_128` | 0.575 [0.508, 0.646] | 0.767 [0.634, 0.887] | 0.666 [0.608, 0.725] | 1.00 |
| `query:rerank_20_128` | 0.563 [0.493, 0.631] | 0.717 [0.585, 0.846] | 0.666 [0.608, 0.725] | 1.00 |
| `query:rerank_30_256` | 0.573 [0.508, 0.639] | 0.747 [0.621, 0.869] | 0.666 [0.608, 0.725] | 1.00 |
| `query:rescore` | 0.516 [0.446, 0.586] | 0.584 [0.456, 0.715] | 0.666 [0.608, 0.725] | 1.00 |
| `query:vector` | 0.548 [0.484, 0.612] | 0.655 [0.522, 0.790] | 0.657 [0.597, 0.718] | 1.00 |

### Metrics, LLM-judged (Gemini), check: condensed lists

Mean over 25 profiles, 95% percentile bootstrap CI over profiles. judged@10 is the share of a variant's top 10 that Gemini graded.

| Variant | NDCG@10 | MRR | Recall@30 | judged@10 |
|---|---|---|---|---|
| `profile:bm25` | 0.503 [0.423, 0.589] | 0.664 [0.533, 0.799] | 0.520 [0.437, 0.603] | 1.00 |
| `profile:fused` | 0.505 [0.425, 0.591] | 0.631 [0.470, 0.785] | 0.549 [0.475, 0.625] | 1.00 |
| `profile:rerank_10_128` | 0.524 [0.442, 0.612] | 0.677 [0.525, 0.824] | 0.549 [0.475, 0.625] | 1.00 |
| `profile:rerank_20_128` | 0.535 [0.456, 0.619] | 0.746 [0.591, 0.889] | 0.549 [0.475, 0.625] | 1.00 |
| `profile:rerank_30_256` | 0.548 [0.471, 0.630] | 0.736 [0.596, 0.864] | 0.549 [0.475, 0.625] | 1.00 |
| `profile:rescore` | 0.546 [0.480, 0.617] | 0.682 [0.558, 0.805] | 0.549 [0.475, 0.625] | 1.00 |
| `profile:vector` | 0.508 [0.434, 0.587] | 0.626 [0.475, 0.773] | 0.523 [0.440, 0.607] | 1.00 |
| `query:bm25` | 0.462 [0.381, 0.549] | 0.558 [0.420, 0.705] | 0.596 [0.509, 0.676] | 1.00 |
| `query:fused` | 0.556 [0.486, 0.631] | 0.743 [0.602, 0.875] | 0.666 [0.608, 0.725] | 1.00 |
| `query:rerank_10_128` | 0.575 [0.508, 0.646] | 0.768 [0.634, 0.887] | 0.666 [0.608, 0.725] | 1.00 |
| `query:rerank_20_128` | 0.563 [0.493, 0.631] | 0.718 [0.585, 0.846] | 0.666 [0.608, 0.725] | 1.00 |
| `query:rerank_30_256` | 0.573 [0.508, 0.639] | 0.747 [0.621, 0.869] | 0.666 [0.608, 0.725] | 1.00 |
| `query:rescore` | 0.516 [0.446, 0.586] | 0.584 [0.456, 0.715] | 0.666 [0.608, 0.725] | 1.00 |
| `query:vector` | 0.548 [0.484, 0.612] | 0.655 [0.522, 0.790] | 0.657 [0.597, 0.718] | 1.00 |
<!-- END:metrics -->

<!-- BEGIN:comparisons -->
### Comparisons, LLM-judged (Gemini)

Paired over profiles: mean difference (a - b), bootstrap 95% CI, two-sided sign-flip permutation p. Verdict: better / worse when the CI excludes 0.

| Comparison | NDCG@10 | MRR | Recall@30 |
|---|---|---|---|
| query: hybrid vs vector | +0.008 [-0.047, +0.060] p=0.776 no clear difference | +0.088 [+0.005, +0.183] p=0.087 better | +0.009 [+0.000, +0.020] p=0.255 no clear difference |
| query: +personalisation vs hybrid | -0.040 [-0.100, +0.013] p=0.194 no clear difference | -0.159 [-0.304, -0.008] p=0.051 worse | +0.000 [+0.000, +0.000] p=1.000 no clear difference |
| query: +rerank 10@128 vs +personalisation | +0.059 [+0.008, +0.114] p=0.049 better | +0.184 [+0.038, +0.327] p=0.023 better | +0.000 [+0.000, +0.000] p=1.000 no clear difference |
| query: +rerank 20@128 vs +personalisation | +0.047 [-0.006, +0.107] p=0.134 no clear difference | +0.134 [+0.016, +0.256] p=0.047 better | +0.000 [+0.000, +0.000] p=1.000 no clear difference |
| query: +rerank 30@256 vs +personalisation | +0.057 [+0.001, +0.123] p=0.091 better | +0.164 [+0.040, +0.288] p=0.019 better | +0.000 [+0.000, +0.000] p=1.000 no clear difference |
| query: vector vs keyword | +0.085 [+0.012, +0.164] p=0.042 better | +0.097 [-0.012, +0.206] p=0.098 no clear difference | +0.061 [+0.022, +0.111] p=0.004 better |
| query: hybrid vs keyword | +0.094 [+0.047, +0.144] p=0.001 better | +0.185 [+0.098, +0.281] p=0.000 better | +0.070 [+0.029, +0.122] p=0.002 better |
| query: +personalisation vs keyword | +0.053 [-0.007, +0.106] p=0.083 no clear difference | +0.026 [-0.125, +0.174] p=0.740 no clear difference | +0.070 [+0.029, +0.122] p=0.002 better |
| query: +rerank 10@128 vs keyword | +0.112 [+0.053, +0.172] p=0.002 better | +0.210 [+0.072, +0.345] p=0.007 better | +0.070 [+0.029, +0.122] p=0.002 better |
| query: +rerank 20@128 vs keyword | +0.100 [+0.033, +0.168] p=0.011 better | +0.160 [+0.035, +0.281] p=0.021 better | +0.070 [+0.029, +0.122] p=0.002 better |
| query: +rerank 30@256 vs keyword | +0.110 [+0.042, +0.179] p=0.004 better | +0.190 [+0.061, +0.314] p=0.010 better | +0.070 [+0.029, +0.122] p=0.002 better |
| profile: hybrid vs vector | -0.002 [-0.034, +0.031] p=0.881 no clear difference | +0.005 [-0.149, +0.148] p=0.950 no clear difference | +0.026 [+0.007, +0.051] p=0.032 better |
| profile: +personalisation vs hybrid | +0.041 [-0.018, +0.100] p=0.200 no clear difference | +0.051 [-0.110, +0.213] p=0.547 no clear difference | +0.000 [+0.000, +0.000] p=1.000 no clear difference |
| profile: +rerank 10@128 vs +personalisation | -0.022 [-0.079, +0.033] p=0.466 no clear difference | -0.005 [-0.130, +0.126] p=0.939 no clear difference | +0.000 [+0.000, +0.000] p=1.000 no clear difference |
| profile: +rerank 20@128 vs +personalisation | -0.011 [-0.060, +0.035] p=0.637 no clear difference | +0.063 [-0.073, +0.202] p=0.378 no clear difference | +0.000 [+0.000, +0.000] p=1.000 no clear difference |
| profile: +rerank 30@256 vs +personalisation | +0.002 [-0.054, +0.055] p=0.955 no clear difference | +0.053 [-0.102, +0.204] p=0.515 no clear difference | +0.000 [+0.000, +0.000] p=1.000 no clear difference |
| profile: vector vs keyword | +0.004 [-0.052, +0.059] p=0.879 no clear difference | -0.038 [-0.221, +0.142] p=0.704 no clear difference | +0.003 [-0.037, +0.050] p=0.904 no clear difference |
| profile: hybrid vs keyword | +0.002 [-0.047, +0.047] p=0.941 no clear difference | -0.033 [-0.214, +0.134] p=0.724 no clear difference | +0.029 [+0.001, +0.069] p=0.132 better |
| profile: +personalisation vs keyword | +0.043 [-0.015, +0.103] p=0.180 no clear difference | +0.019 [-0.140, +0.174] p=0.827 no clear difference | +0.029 [+0.001, +0.069] p=0.132 better |
| profile: +rerank 10@128 vs keyword | +0.021 [-0.033, +0.072] p=0.460 no clear difference | +0.013 [-0.141, +0.163] p=0.871 no clear difference | +0.029 [+0.001, +0.069] p=0.132 better |
| profile: +rerank 20@128 vs keyword | +0.032 [-0.010, +0.075] p=0.168 no clear difference | +0.082 [-0.048, +0.209] p=0.231 no clear difference | +0.029 [+0.001, +0.069] p=0.132 better |
| profile: +rerank 30@256 vs keyword | +0.045 [-0.003, +0.093] p=0.089 no clear difference | +0.072 [-0.061, +0.207] p=0.318 no clear difference | +0.029 [+0.001, +0.069] p=0.132 better |
| query+profile vs profile only: bm25 | -0.041 [-0.131, +0.048] p=0.392 no clear difference | -0.105 [-0.289, +0.077] p=0.297 no clear difference | +0.076 [-0.061, +0.202] p=0.275 no clear difference |
| query+profile vs profile only: vector | +0.040 [-0.030, +0.113] p=0.289 no clear difference | +0.030 [-0.116, +0.184] p=0.717 no clear difference | +0.134 [+0.010, +0.257] p=0.047 better |
| query+profile vs profile only: fused | +0.051 [-0.032, +0.133] p=0.242 no clear difference | +0.113 [-0.068, +0.297] p=0.248 no clear difference | +0.117 [+0.003, +0.229] p=0.059 better |
| query+profile vs profile only: rescore | -0.030 [-0.132, +0.067] p=0.570 no clear difference | -0.098 [-0.292, +0.096] p=0.341 no clear difference | +0.117 [+0.003, +0.229] p=0.059 better |
| query+profile vs profile only: rerank_10_128 | +0.051 [-0.040, +0.141] p=0.285 no clear difference | +0.091 [-0.107, +0.294] p=0.395 no clear difference | +0.117 [+0.003, +0.229] p=0.059 better |
| query+profile vs profile only: rerank_20_128 | +0.028 [-0.080, +0.129] p=0.616 no clear difference | -0.028 [-0.208, +0.157] p=0.770 no clear difference | +0.117 [+0.003, +0.229] p=0.059 better |
| query+profile vs profile only: rerank_30_256 | +0.025 [-0.063, +0.110] p=0.595 no clear difference | +0.012 [-0.143, +0.178] p=0.881 no clear difference | +0.117 [+0.003, +0.229] p=0.059 better |
<!-- END:comparisons -->

<!-- BEGIN:subsets -->
### Subsets: source snippets and stale postings (query mode)

The same rankings with some jobs removed (later jobs move up), scored with condensed lists, LLM-judged (Gemini). Mean NDCG@10 [95% CI].

| Variant | all pairs | without source snippets | posted within 90 days |
|---|---|---|---|
| `bm25` | 0.462 [0.381, 0.549] | 0.472 [0.385, 0.561] | 0.509 [0.427, 0.593] |
| `vector` | 0.548 [0.484, 0.612] | 0.541 [0.483, 0.601] | 0.567 [0.503, 0.633] |
| `fused` | 0.556 [0.486, 0.631] | 0.545 [0.475, 0.620] | 0.580 [0.507, 0.652] |
| `rescore` | 0.516 [0.446, 0.586] | 0.548 [0.466, 0.628] | 0.550 [0.472, 0.629] |
| `rerank_10_128` | 0.575 [0.508, 0.646] | 0.564 [0.492, 0.637] | 0.581 [0.511, 0.653] |
| `rerank_20_128` | 0.563 [0.493, 0.631] | 0.559 [0.488, 0.631] | 0.574 [0.494, 0.650] |
| `rerank_30_256` | 0.573 [0.508, 0.639] | 0.579 [0.509, 0.655] | 0.600 [0.527, 0.674] |
| hybrid vs vector | +0.008 [-0.047, +0.060] no clear difference | +0.004 [-0.040, +0.046] no clear difference | +0.012 [-0.038, +0.059] no clear difference |
| +personalisation vs hybrid | -0.040 [-0.100, +0.013] no clear difference | +0.004 [-0.072, +0.075] no clear difference | -0.030 [-0.094, +0.029] no clear difference |
| +rerank 10@128 vs +personalisation | +0.059 [+0.008, +0.114] better | +0.015 [-0.055, +0.088] no clear difference | +0.032 [-0.022, +0.090] no clear difference |
| +rerank 20@128 vs +personalisation | +0.047 [-0.006, +0.107] no clear difference | +0.011 [-0.054, +0.077] no clear difference | +0.024 [-0.033, +0.086] no clear difference |
| +rerank 30@256 vs +personalisation | +0.057 [+0.001, +0.123] better | +0.031 [-0.032, +0.096] no clear difference | +0.051 [-0.006, +0.112] no clear difference |
| vector vs keyword | +0.085 [+0.012, +0.164] better | +0.069 [-0.004, +0.146] no clear difference | +0.058 [-0.014, +0.136] no clear difference |
| hybrid vs keyword | +0.094 [+0.047, +0.144] better | +0.073 [+0.025, +0.126] better | +0.070 [+0.021, +0.124] better |

- all pairs: every job; 0 jobs removed, 1000 labelled pairs left.
- without source snippets: jobs whose source gives only a snippet (description_quality = snippet: Adzuna) removed; 335 jobs removed, 855 labelled pairs left.
- posted within 90 days: jobs posted more than 90 days before the snapshot removed; 997 jobs removed, 803 labelled pairs left.
<!-- END:subsets -->

<!-- BEGIN:sensitivity -->
### Sensitivity: final labels vs v2 labels (Gemini, NDCG@10)

| Variant | final | v2 | delta |
|---|---:|---:|---:|
| `profile:bm25` | 0.503 | 0.520 | -0.017 |
| `profile:fused` | 0.505 | 0.516 | -0.011 |
| `profile:rerank_10_128` | 0.524 | 0.526 | -0.002 |
| `profile:rerank_20_128` | 0.535 | 0.546 | -0.012 |
| `profile:rerank_30_256` | 0.548 | 0.559 | -0.011 |
| `profile:rescore` | 0.546 | 0.545 | +0.001 |
| `profile:vector` | 0.508 | 0.524 | -0.017 |
| `query:bm25` | 0.462 | 0.468 | -0.005 |
| `query:fused` | 0.556 | 0.575 | -0.019 |
| `query:rerank_10_128` | 0.575 | 0.592 | -0.017 |
| `query:rerank_20_128` | 0.563 | 0.586 | -0.023 |
| `query:rerank_30_256` | 0.573 | 0.590 | -0.018 |
| `query:rescore` | 0.516 | 0.523 | -0.008 |
| `query:vector` | 0.548 | 0.592 | -0.044 |

| Comparison | final | v2 | same verdict |
|---|---|---|---|
| query: hybrid vs vector | +0.008 [-0.047, +0.060] no clear difference | -0.017 [-0.080, +0.041] no clear difference | yes |
| query: +personalisation vs hybrid | -0.040 [-0.100, +0.013] no clear difference | -0.052 [-0.108, +0.003] no clear difference | yes |
| query: +rerank 10@128 vs +personalisation | +0.059 [+0.008, +0.114] better | +0.068 [+0.011, +0.125] better | yes |
| query: +rerank 20@128 vs +personalisation | +0.047 [-0.006, +0.107] no clear difference | +0.062 [+0.006, +0.125] better | NO |
| query: +rerank 30@256 vs +personalisation | +0.057 [+0.001, +0.123] better | +0.067 [+0.008, +0.132] better | yes |
| query: vector vs keyword | +0.085 [+0.012, +0.164] better | +0.124 [+0.049, +0.207] better | yes |
| query: hybrid vs keyword | +0.094 [+0.047, +0.144] better | +0.108 [+0.066, +0.152] better | yes |
| query: +personalisation vs keyword | +0.053 [-0.007, +0.106] no clear difference | +0.056 [+0.001, +0.106] better | NO |
| query: +rerank 10@128 vs keyword | +0.112 [+0.053, +0.172] better | +0.124 [+0.072, +0.176] better | yes |
| query: +rerank 20@128 vs keyword | +0.100 [+0.033, +0.168] better | +0.118 [+0.056, +0.185] better | yes |
| query: +rerank 30@256 vs keyword | +0.110 [+0.042, +0.179] better | +0.123 [+0.059, +0.191] better | yes |
| profile: hybrid vs vector | -0.002 [-0.034, +0.031] no clear difference | -0.008 [-0.042, +0.025] no clear difference | yes |
| profile: +personalisation vs hybrid | +0.041 [-0.018, +0.100] no clear difference | +0.029 [-0.026, +0.084] no clear difference | yes |
| profile: +rerank 10@128 vs +personalisation | -0.022 [-0.079, +0.033] no clear difference | -0.019 [-0.071, +0.033] no clear difference | yes |
| profile: +rerank 20@128 vs +personalisation | -0.011 [-0.060, +0.035] no clear difference | +0.001 [-0.038, +0.041] no clear difference | yes |
| profile: +rerank 30@256 vs +personalisation | +0.002 [-0.054, +0.055] no clear difference | +0.014 [-0.031, +0.061] no clear difference | yes |
| profile: vector vs keyword | +0.004 [-0.052, +0.059] no clear difference | +0.005 [-0.048, +0.058] no clear difference | yes |
| profile: hybrid vs keyword | +0.002 [-0.047, +0.047] no clear difference | -0.003 [-0.046, +0.036] no clear difference | yes |
| profile: +personalisation vs keyword | +0.043 [-0.015, +0.103] no clear difference | +0.025 [-0.028, +0.079] no clear difference | yes |
| profile: +rerank 10@128 vs keyword | +0.021 [-0.033, +0.072] no clear difference | +0.007 [-0.046, +0.057] no clear difference | yes |
| profile: +rerank 20@128 vs keyword | +0.032 [-0.010, +0.075] no clear difference | +0.027 [-0.011, +0.067] no clear difference | yes |
| profile: +rerank 30@256 vs keyword | +0.045 [-0.003, +0.093] no clear difference | +0.039 [-0.006, +0.088] no clear difference | yes |
| query+profile vs profile only: bm25 | -0.041 [-0.131, +0.048] no clear difference | -0.052 [-0.129, +0.025] no clear difference | yes |
| query+profile vs profile only: vector | +0.040 [-0.030, +0.113] no clear difference | +0.068 [-0.007, +0.142] no clear difference | yes |
| query+profile vs profile only: fused | +0.051 [-0.032, +0.133] no clear difference | +0.059 [-0.017, +0.132] no clear difference | yes |
| query+profile vs profile only: rescore | -0.030 [-0.132, +0.067] no clear difference | -0.022 [-0.110, +0.067] no clear difference | yes |
| query+profile vs profile only: rerank_10_128 | +0.051 [-0.040, +0.141] no clear difference | +0.065 [-0.009, +0.139] no clear difference | yes |
| query+profile vs profile only: rerank_20_128 | +0.028 [-0.080, +0.129] no clear difference | +0.039 [-0.055, +0.129] no clear difference | yes |
| query+profile vs profile only: rerank_30_256 | +0.025 [-0.063, +0.110] no clear difference | +0.031 [-0.057, +0.116] no clear difference | yes |

ADR 0003 choice under v2 labels: `rerank_10_128`.
<!-- END:sensitivity -->

## 7. Do the conclusions hold under every judge?

<!-- BEGIN:robustness -->
### Robustness: do the conclusions hold under every judge?

NDCG@10 difference (a - b) and 95% CI per judge. The reference is Gemini on all pairs; the blind columns use condensed lists over the 120 blind pairs (about 5 per profile), so they are much noisier. holds = same verdict as the reference; weaker = the reference's difference is not clear under this judge; differs = this judge finds a difference the reference does not; reverses = opposite verdicts.

| Comparison | gemini (all pairs) | gemini (blind pairs) | groq (blind pairs) | cowork (blind pairs) | majority (blind pairs) |
|---|---|---|---|---|---|
| query: hybrid vs keyword | +0.094 [+0.047, +0.144] better (holds) | +0.044 [+0.001, +0.093] better (holds) | +0.045 [+0.001, +0.097] better (holds) | +0.059 [+0.013, +0.115] better (holds) | +0.043 [+0.002, +0.092] better (holds) |
| query: vector vs keyword | +0.085 [+0.012, +0.164] better (holds) | +0.012 [-0.032, +0.059] no clear difference (weaker) | +0.041 [-0.014, +0.105] no clear difference (weaker) | +0.031 [-0.028, +0.104] no clear difference (weaker) | +0.015 [-0.030, +0.062] no clear difference (weaker) |
| query: hybrid vs vector | +0.008 [-0.047, +0.060] no clear difference (holds) | +0.032 [+0.004, +0.066] better (differs) | +0.004 [-0.023, +0.037] no clear difference (holds) | +0.027 [-0.007, +0.066] no clear difference (holds) | +0.029 [+0.003, +0.062] better (differs) |
| query: +personalisation vs hybrid | -0.040 [-0.100, +0.013] no clear difference (holds) | -0.025 [-0.078, +0.022] no clear difference (holds) | -0.012 [-0.056, +0.026] no clear difference (holds) | -0.058 [-0.109, -0.013] worse (differs) | -0.044 [-0.094, -0.000] worse (differs) |
| query: +rerank 10@128 vs +personalisation | +0.059 [+0.008, +0.114] better (holds) | +0.036 [-0.006, +0.082] no clear difference (weaker) | +0.022 [-0.016, +0.058] no clear difference (weaker) | +0.055 [+0.015, +0.098] better (holds) | +0.049 [+0.007, +0.092] better (holds) |
| query: +rerank 20@128 vs +personalisation | +0.047 [-0.006, +0.107] no clear difference (holds) | +0.024 [-0.004, +0.055] no clear difference (holds) | +0.023 [-0.004, +0.052] no clear difference (holds) | +0.034 [+0.003, +0.069] better (differs) | +0.033 [+0.005, +0.064] better (differs) |
| query: +rerank 30@256 vs +personalisation | +0.057 [+0.001, +0.123] better (holds) | +0.023 [-0.003, +0.052] no clear difference (weaker) | +0.014 [-0.012, +0.041] no clear difference (weaker) | +0.036 [+0.004, +0.072] better (holds) | +0.033 [+0.006, +0.063] better (holds) |
| profile: hybrid vs keyword | +0.002 [-0.047, +0.047] no clear difference (holds) | +0.012 [-0.024, +0.060] no clear difference (holds) | +0.027 [-0.011, +0.075] no clear difference (holds) | +0.031 [-0.009, +0.082] no clear difference (holds) | +0.020 [-0.017, +0.070] no clear difference (holds) |
| profile: vector vs keyword | +0.004 [-0.052, +0.059] no clear difference (holds) | +0.002 [-0.059, +0.073] no clear difference (holds) | +0.009 [-0.047, +0.077] no clear difference (holds) | +0.024 [-0.024, +0.081] no clear difference (holds) | +0.011 [-0.043, +0.080] no clear difference (holds) |
| profile: hybrid vs vector | -0.002 [-0.034, +0.031] no clear difference (holds) | +0.011 [-0.027, +0.051] no clear difference (holds) | +0.018 [-0.015, +0.053] no clear difference (holds) | +0.007 [-0.020, +0.034] no clear difference (holds) | +0.009 [-0.016, +0.035] no clear difference (holds) |
| profile: +personalisation vs hybrid | +0.041 [-0.018, +0.100] no clear difference (holds) | +0.014 [-0.025, +0.057] no clear difference (holds) | +0.021 [-0.025, +0.071] no clear difference (holds) | +0.012 [-0.036, +0.063] no clear difference (holds) | +0.012 [-0.033, +0.064] no clear difference (holds) |
| profile: +rerank 10@128 vs +personalisation | -0.022 [-0.079, +0.033] no clear difference (holds) | -0.006 [-0.046, +0.031] no clear difference (holds) | -0.007 [-0.058, +0.040] no clear difference (holds) | -0.004 [-0.050, +0.038] no clear difference (holds) | -0.002 [-0.050, +0.039] no clear difference (holds) |
| profile: +rerank 20@128 vs +personalisation | -0.011 [-0.060, +0.035] no clear difference (holds) | -0.005 [-0.038, +0.024] no clear difference (holds) | -0.001 [-0.048, +0.043] no clear difference (holds) | -0.010 [-0.050, +0.024] no clear difference (holds) | -0.003 [-0.047, +0.031] no clear difference (holds) |
| profile: +rerank 30@256 vs +personalisation | +0.002 [-0.054, +0.055] no clear difference (holds) | -0.002 [-0.032, +0.026] no clear difference (holds) | -0.001 [-0.042, +0.042] no clear difference (holds) | -0.003 [-0.037, +0.027] no clear difference (holds) | +0.002 [-0.035, +0.034] no clear difference (holds) |

Rerank setting each judge's labels choose (query mode, same rule): gemini (all pairs): `rerank_10_128`, gemini (blind pairs): `rescore`, groq (blind pairs): `rescore`, cowork (blind pairs): `rerank_10_128`, majority (blind pairs): `rerank_10_128`.
<!-- END:robustness -->

## 8. Which rerank setting for interactive search (ADR 0003)

<!-- BEGIN:adr -->
### ADR 0003: the interactive rerank setting

Rule (paired form, owner decision 2026-11-27): eligible = within 0.01 NDCG@10 of the best setting, or a paired CI of the difference to the best that includes 0; choose the eligible setting with the lowest single-search p95.

**Interactive search (query mode)**: best `rerank_10_128`; eligible ['rerank_10_128', 'rerank_20_128', 'rerank_30_256']; chosen **`rerank_10_128`**, p95 331 ms, misses the 300 ms target.

| Setting | NDCG@10 | difference to best | p50 / p95 ms |
|---|---|---|---|
| `rescore` | 0.516 [0.446, 0.586] | -0.059 [-0.114, -0.008] | 62 / 75 |
| `rerank_10_128` | 0.575 [0.508, 0.646] | (best) | 292 / 331 |
| `rerank_20_128` | 0.563 [0.493, 0.631] | -0.012 [-0.044, +0.021] | 506 / 593 |
| `rerank_30_256` | 0.573 [0.508, 0.639] | -0.002 [-0.040, +0.037] | 1588 / 1817 |

**Digest (profile mode, for reference)**: ADR 0003 keeps the digest at 30@256 "unless that table shows it does not help" (nobody waits for it). 30@256 vs no rerank, profile mode: +0.002 [-0.054, +0.055] (no clear difference); the interactive rule would pick `rescore`, which does not apply to the digest.

| Setting | NDCG@10 | difference to best | p50 / p95 ms |
|---|---|---|---|
| `rescore` | 0.546 [0.480, 0.617] | -0.002 [-0.055, +0.054] | 62 / 75 |
| `rerank_10_128` | 0.524 [0.442, 0.612] | -0.024 [-0.075, +0.017] | 292 / 331 |
| `rerank_20_128` | 0.535 [0.456, 0.619] | -0.013 [-0.038, +0.013] | 506 / 593 |
| `rerank_30_256` | 0.548 [0.471, 0.630] | (best) | 1588 / 1817 |

Latency: docs/bench/search-2026-11-24.md (Phase 4 candidates, one search at a time).

Robustness of the choice (same rule): gemini (all pairs): `rerank_10_128`, gemini (blind pairs): `rescore`, groq (blind pairs): `rescore`, cowork (blind pairs): `rerank_10_128`, majority (blind pairs): `rerank_10_128`; under the v2 labels: `rerank_10_128`.
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
0.02 below `eval/gate/baseline.json`. On 2026-11-28 it took 17.5 s (about 25 s with
the container start) on the owner's laptop and gave identical numbers on two runs. Its
baseline was re-measured on the final labels that day, and the CI step is blocking.

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
