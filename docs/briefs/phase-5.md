# Phase 5: Profile, matches UI, and measured ranking changes

Drafted 2026-11-27, revised the same day with the owner's decisions (listed at the end).

Phase 5 has three sub-phases:

- **5a: UI and profile** (branch `phase-5a-ui`, worktree `Job Match Ai-p5`). It runs now,
  alongside Phase 4. It uses no Docker and makes no change to retrieval, ranking,
  embeddings or ingestion.
- **5b: ranking changes** (branch `phase-5b-ranking`). It starts after Phase 4 merges.
  Every change is measured with the Phase 4 harness before it is switched on.
- **5c: resume and stored profile** (branch `phase-5c-profile`). It starts once Docker is
  free. It covers resume upload and parsing into a `CandidateProfile` with spans, the
  `candidate_profiles`, `dealbreakers` and `job_feedback` tables, the profile and
  feedback API, and the job fields that 5a needs but the API does not return yet (listed
  in the API gaps section below).

Sources: [PLAN.md](../../PLAN.md) (UI direction, Phase 5 row),
[backlog-from-hireplz.md](backlog-from-hireplz.md), and `backlog-from-phase-4.md`. The
Phase 4 backlog is on `phase-4-eval` and reaches main when Phase 4 merges.

**No human labelling anywhere in Phase 5.** Every check gets its reference from the
Phase 4 LLM judges, from mechanical rules, or by construction, and the report names
which. No result is described as human-validated.

---

## 5a: UI and profile

### Constraints

- No Docker commands until the owner says Phase 4's judging is done. The frontend runs
  with `npm run dev` against typed test data.
- Test data follows the existing API schemas exactly: `SearchProfile`, `DealbreakerRule`
  (the `kind` union in `app/retrieval/rules.py`), and `SearchResponse` with
  `SearchResult`, `Explanation`, `RuledOut` and `PoolSummary`. It is typed from the
  generated `src/lib/api-types.ts`, so a test record whose shape drifts from the API
  fails the typecheck. Job fields the API lacks are a separate, optional type (see API
  gaps below).
- No MSW and no new runtime dependency. Test data comes from a plain implementation of
  the data interface.
- No personal data leaves the browser, and 5a makes no LLM calls. The profile and
  feedback live in `localStorage` on this device only. A "Clear my data" button deletes
  them.
- Visual direction comes from PLAN.md and the existing tokens in `globals.css`: paper
  `#F4F0E6`, forest-green accent `#1F5A44`, and red only for errors. No purple, no navy,
  no gradients, no glassy cards, no emoji, and no illustration filler. Light theme only
  in 5a.
- **Fonts:** **Newsreader** for headings (serif) and **Inter Tight** for body text
  (sans). Both are SIL Open Font License and both are already in the repo. They load
  through `next/font/google`, which downloads the files at build time and serves them
  from our own origin, so the browser never contacts Google. JetBrains Mono stays for
  the few numeric or ID strings.

### Test data: about 12 fictional postings that cover the edge cases

All companies, people and text are made up, and no snapshot posting is copied. The set
covers each of these at least once (one posting may cover several):

| Edge case | How it shows |
|---|---|
| Short source snippet (Adzuna-style) | "Short description from source" note; no expand control |
| Posted more than 90 days ago | "Posted 4 months ago" |
| Stale match, under the API's 365-day limit | "Posted 11 months ago · reposted 3 times · seen at 2 sources" (340 days) |
| Posted more than 365 days ago | only as a ruled-out posting (790 days, breaks "Posted in the last 365 days") |
| No salary stated | "Salary not stated" |
| INR salary | "₹18–24 LPA" in the original currency (the USD figure is never the headline) |
| USD, remote | "$140,000–$170,000 a year · Remote" |
| Internship | the employment type shown; stipend shown per month as stated |
| Staffing agency | "Posted by a staffing agency" |
| Contract role | the employment type shown |
| Worldwide eligibility | "Open to applicants worldwide" |
| Ruled out, one per dealbreaker type | all 9 kinds: `work_eligibility`, `workplace`, `min_salary_usd`, `seniority`, `employment_type`, `exclude_industries`, `exclude_companies`, `startup_backed`, `posted_within_days`, each with both a "violates" and an "unknown under strict" example where the kind allows it |
| Long description | collapsed to a few lines with a "Show full description" toggle |
| Missing company logo | monogram fallback (the first letter on a tinted square) |

### Screens and components, in build order

**First: the daily list and the match card.** These are built with test data in every
state, then I send screenshots and stop for review.

1. **Daily matches list.**
   - At most five matches (per PLAN §1), plus a collapsible "Ruled out today" section
     and the pool line ("Searched 23,705 postings · updated 3 hours ago", from
     `PoolSummary`).
   - A route at `/matches`. With test data it needs no sign-in, because the backend is
     not running. With the API it uses the existing auth guard.
2. **Match card.**
   - **Why it matches** is built only from the structured `Explanation`: matched skills,
     experience fit, and the preferences met. The optional LLM sentence
     (`ExplanationSentence`) appears below it, only when `status` is `ok`. It never adds
     a claim the structured part doesn't make, and the backend already drops a sentence
     that names a skill missing from the explanation. The card reads complete without it.
   - **Gaps**: missing skills, experience below or above the range, unmet preferences,
     and flags for dealbreakers that couldn't be checked ("Salary not listed: check
     before applying").
   - **Salary**: shown as stated in its original currency and interval, or "Salary not
     stated".
   - **Facts line**, with only factual signals and no "ghost job" label: "Posted 14
     months ago · reposted 3 times · seen at 2 sources". Each part shows only when its
     data exists.
   - **"Short description from source"** note on snippet postings.
   - **Feedback**: "Save", and "Not for me" with a reason (wrong level, location,
     salary, not interested in this company, other with an optional note). Both can be
     undone. They are stored locally in the shape the personalisation API will need:

     ```ts
     type JobFeedback = {
       job_id: string;              // uuid
       action: "saved" | "dismissed";
       reason: "wrong_level" | "location" | "salary" | "company" | "other" | null; // dismissed only
       note: string | null;         // "other" only, at most 200 characters
       created_at: string;          // ISO 8601
     };
     ```

     This is PLAN's `job_feedback` table plus a reason. 5c adds `applied` and the endpoint.
   - **Ruled-out card**: a compact variant that shows each `RuleBreach` (violates vs
     unknown, with its rule and reason).
3. **States for the list**:
   - Loading: skeleton cards with `aria-busy` and a status message.
   - Empty: no profile yet (link to onboarding), profile but no matches, or every match
     ruled out.
   - Error: API down, 401 (goes to login), 429 (shows when to retry), and degraded
     stages (a quiet note).
   - A dev-only state switcher (`?state=loading|empty|error…`) so every state can be
     reviewed and screenshotted.

**Then, after review:** onboarding (resume upload placeholder, skills, level,
location/remote, dealbreakers with the per-rule `strict` switch), the profile page, and
"Clear my data".

### Quality bar

- Responsive from 360 px up.
- Everything works by keyboard: logical tab order, visible focus, a skip link, Escape
  closes the reason menu, and focus returns to its trigger.
- Labelled controls, and `aria-live` for asynchronous changes and feedback
  confirmations.
- AA contrast on paper and surface.

### Data layer

The data layer (`src/lib/data/`) has one interface and two implementations:

- `fixtures`: the default in 5a.
- `api`: calls `POST /api/v1/search` (profile mode, `limit` 5) and
  `POST /api/v1/search/explanation`. It's wired and typechecked, and switched on in 5c.

`NEXT_PUBLIC_DATA_SOURCE` selects the implementation.

### API gaps (for 5c, not changed in 5a)

The card displays fields that the database has, or will have after Phase 4, but that
`JobSummary` does not return. In 5a they are an optional `JobExtras` type, filled only in
test data:

- `description`, `description_quality`
- `eligibility_scope`, `work_countries`
- `poster_type`, `engagement_type`
- `alternate_sources` count
- repost count
- `salary_refusal`
- `logo_url` (no logo source exists yet)

5c adds them to the response, which is an additive API change. Until then the `api`
implementation shows only what the API returns, and each missing part is hidden, never
guessed.

Profile changes for 5c (from 5a, 2026-11-28):

- **Salary currency:** the backend accepts a minimum salary in its own currency (INR in
  LPA or USD), and the INR rate becomes configurable there. In 5a the browser converts
  LPA to `min_salary_usd` with one fixed constant (`frontend/src/lib/fx.ts`: 93.93 INR per
  USD, the ECB rate of 2026-11-16 from `fx_rates.yaml`) and keeps what was typed beside
  the rule.
- **Field:** a real `field` property on the backend profile. In 5a it is sent as
  `SearchRequest.query`, because `SearchProfile` has none.

Test data never exceeds what the API accepts: a test checks every test-data request (and
the test responses) against `openapi.json`.

### Checks

- `npm run lint`, `typecheck`, `build` and `test`. Vitest, Testing Library and axe-core
  run as a step inside the existing `Frontend (lint, types, build, audit)` CI job. No job
  is renamed or added.
- Component tests on the test data cover every edge case in the table above, the
  feedback round-trip through `localStorage`, and an axe check per state.
- Screenshots at 360 px and 1280 px.

---

## 5b: Ranking changes (after Phase 4 merges)

### How 5b is measured: build all, judge once

Judging is the scarce resource.
- **Gemini's free tier allows about 480 requests a day**, resetting at midnight Pacific
  (`DAILY_REQUESTS` in `backend/app/eval/quota.py`).
- **Requests are not pairs:** on 2026-11-28, 451 requests judged 398 pairs, the rest
  being retried 503s (decision log, 2026-11-28).
- **It allows 15 calls a minute** (decision log, 2026-11-26).
So 5b does not judge item by item. It builds every variant first, collects every new
pair they produce, judges that union in **one** fill, and only then measures.

1. **Build all five behind flags.** B1–B5 each become a named variant with a config flag
   (default off) and their own unit tests. Combinations are flag sets, not new code. No
   flag is switched on in production during this step.
2. **Dry run every configuration, with no judging.**
   - Run each configuration below on the frozen snapshot `2026-11-25`, in `query` and
     `profile` mode, over the 25 profiles. Append the rankings to `runs.jsonl`.
   - CPU estimate given before the run: about 12 configurations × 50 searches, with
     rerank.
   - B3's blocker extraction and B5's query parsing run here too:
     - B3 runs rules first, then the LLM fallback on public JD text, using Groq first so
       it doesn't eat the Gemini judging quota.
     - B5 runs on the production path (personal: Groq → Ollama, even though the profiles
       are fictional).
3. **Collect the union.**
   - Take every (profile, mode, job) in any configuration's top 10 that has no grade yet.
   - The rubric and judge input version must be identical to the Phase 4 baseline's
     final labels (`eval_judge/v1`, current input version, `gemini-3.5-flash-lite`).
     Otherwise old and new grades aren't comparable.
4. **Estimate pairs and quota days up front, before any judging.**
   - The exact union size comes from step 3. Today's range, to be replaced by that
     number:

     | Source | New pairs (estimate) | Basis |
     |---|---|---|
     | Each single variant | 50–250 of its 500 top-10 slots | Reorderings mostly reshuffle the pooled top 10; B5 changes query mode most |
     | Union over all configurations | **≈600–1,200** | Variants overlap heavily; combinations add few pairs beyond their parts |
     | Calibration re-judge | 50 | A seeded sample of already-graded pairs, re-judged to show the judge hasn't drifted (agreement reported) |
     | B3 reference extraction | ≈300 JDs | The Gemini reference for B3's agreement check (public JD text) |
     | **Total Gemini calls** | **≈950–1,550** | |
     | **Quota days** | **≈2–4** at 480 requests a day, allowing for ≈13% retries (451 requests for 398 pairs on 2026-11-28) | Runs unattended with `until_done` (waits out each daily reset) |

   - The owner OKs the exact count and the day estimate before the fill starts.
5. **One fill.** `make eval-fill` judges the whole union in a single resumable run. The
   report states how many pairs were added per configuration, so pool bias is visible.
6. **Measure everything against the Phase 4 baseline.**
   - Use `make eval FULL=1` for each configuration: NDCG@10, MRR and Recall@30 with 95%
     bootstrap CIs over the 25 profiles.
   - For each configuration, report **ΔNDCG@10 against the current production variant**
     (paired by profile and mode), with a **95% paired-bootstrap CI**. Do this on all
     pairs and on the **posted within 90 days** subset. MRR and Recall@30 are reported
     the same way.
   - **The study is underpowered, and the report says so plainly.** With n = 25 profiles
     and 12 configurations, small real effects can't be told apart from noise.
     Decisions therefore rest on **effect sizes with their CIs**, not on significance.
   - Paired-test p-values are still reported, **Holm-corrected and raw**, for
     transparency only. They don't drive any decision.
   - Each item's own check (table below) is reported beside its metrics.
7. **Robustness:** for the combined configuration and any item proposed for switching
   on, check that the result holds under Groq, Cowork and the 3-judge majority on the
   blind pairs (§7 of the Phase 4 report).
8. **Decision rule** (owner, 2026-11-28). The target is the **combined** configuration.
   - **"Nothing drops" means non-inferiority:** the **lower bound of the 95% CI of
     ΔNDCG@10 against the baseline must be above −0.01**, on all pairs **and** on the
     ≤90-day subset. A CI that crosses −0.01 is "not shown non-inferior", and the change
     stays off, even if its point estimate is positive.
   - An item stays in the combined configuration only if:
     - **its leave-one-out effect** (combined minus combined-without-it) has a point
       estimate ≥ 0, with a CI lower bound above −0.01 on both subsets;
     - the **combined configuration** is non-inferior to the baseline on both subsets;
       and
     - **its own check** passes.
   - **Improvements are reported with their CI, never as "significant".** A positive
     point estimate whose CI includes 0 is written as "no clear change; not worse".
   - Then re-measure `gate/baseline.json` for the final flag set, give the reasons in the
     decision log, and let the CI gate guard it.

All grades are LLM-judged, and every table says so. Before any step using more than 5
minutes of full CPU, state the runtime estimate.

#### Configurations measured (12)

| # | Configuration | Why |
|---|---|---|
| 1–5 | B1, B2, B3, B4, B5 alone | Each item's effect in isolation |
| 6 | **All five** (B1+B2+B3+B4+B5) | The candidate production setting |
| 7–11 | All five minus one (−B1, −B2, −B3, −B4, −B5) | Each item's marginal effect alongside the others. This is the leave-one-out the decision rule uses. |
| 12 | B1+B2 | B2's age signals overlap with B1's freshness, so this checks old postings aren't penalised twice |

- **Not measured:** the other 19 of the 32 possible flag combinations (12 measured plus
  the baseline with every flag off). A full factorial would
  multiply pairs, quota days and the number of tests, for little decision value.
- **B5 only changes `query` mode.** In `profile` mode, configurations with and without
  B5 rank identically, which the report states rather than counting twice.

### Items, in order

#### B0 (first, before B1): profile-mode retrieval and personalisation diagnosis

From the Phase 4 PR (#6) description, as written there:

> **B0. Profile-mode retrieval and personalisation diagnosis.**
> Phase 4 (LLM-judged (Gemini), eval-2026-11-25) found:
> - in profile mode nothing beats keyword search: hybrid vs keyword +0.002 [−0.047, +0.047], +rerank 10@128 vs keyword +0.021 [−0.033, +0.072], 30@256 vs no rerank +0.002 [−0.054, +0.055];
> - in query mode the personalised re-score does not help: NDCG@10 −0.040 [−0.100, +0.013]; MRR −0.159 [−0.304, −0.008], worse; worse NDCG@10 under the Cowork and majority blind-pair labels; +0.004 [−0.072, +0.075] without source snippets.
>
> Diagnose:
> - how the profile is turned into a query: the field currently stuffed into the query text, skills weighting, level;
> - why hybrid ≈ keyword in profile mode;
> - why the re-score pushes the first relevant job down.
>
> Measure each fix with the same harness: frozen snapshot 2026-11-25, final labels, judged@10 checked, with new top-10 jobs judged before scoring.
> **Success:** profile-mode pipeline vs keyword with a paired 95% CI above 0.
> (Review note: the per-subset personalisation result is no clear difference without snippets, so "hurts on full-text postings" is a hypothesis to test, not a finding.)

**How B0 fits the plan above** (my reading; correct me if wrong):
- **The diagnosis comes first and needs no new judging.** It works from the existing
  final labels and the rankings already in `runs.jsonl`: where the first relevant job
  lands, what the profile query looks like, and which rescore components move it.
- **Any fix it finds becomes a flagged variant**, like B1–B5. Its new top-10 jobs join
  the same union and the same single Gemini fill (step 3), so B0 adds configurations,
  not a second fill. The exact count is given in step 4 before judging.
- **B0's success test differs from the others' non-inferiority rule.** It is
  superiority: the profile-mode pipeline against keyword, with a paired 95% CI above 0.
  Until a fix meets that, the report keeps profile mode under "claims we will not make"
  (`docs/claims.md`).
- **"Personalisation hurts" is a hypothesis to test, not a finding.** The report words it
  that way.

#### B1–B5

| # | Item | What changes | Its own check (beside the steps above) |
|---|---|---|---|
| B1 | **Freshness / stale filter** (Phase 4 backlog) | Demote postings more than 90 days old. Hide postings more than 365 days old unless `is_evergreen`. The age display is already in 5a. | Main metrics on the within-90-days subset vs all pairs. Count of judged-relevant pairs (grade 2 or more) that the 365-day hide removes, listed in the report as its cost. Today 103 of the 1,000 pairs are more than 365 days old. |
| B3 | **Requirement blockers** (hireplz). Early, because the Phase 4 truncation check showed that grades change when the description is cut, often before its experience requirement (8 of 30 cut pairs changed vs 0 of 29 controls; eval/report.md). That experience mismatch is what moves them is a hypothesis. | From each JD: minimum years, degree, language, work authorisation, location or work mode, certification. Rules run first, with LLM fallback (`data_class` public, JD text only). Each blocker is graded hard, medium or soft, then met or unmet against the profile. An unmet hard blocker caps the fit label at "Stretch" and appears in `Explanation`. | **Agreement with an LLM reference, never called human-validated.** (a) A mechanical reference for years of experience and degree: deterministic regexes over the JD text, reported as precision and recall of the extractor against them. (b) Gemini extraction on public JD text for the other types, with agreement per type. (c) Cowork spot-checks a stratified sample of (b) as an LLM judge, and its agreement is reported. On eval pairs: the judge grade distribution for jobs with an unmet hard blocker, then the demotion variant through the steps above. |
| B4 | **Skill adjacency** (hireplz) | A curated dictionary of substitutable skills (pytorch↔tensorflow, postgresql↔mysql, aws↔gcp↔azure, react↔vue↔angular, kafka↔rabbitmq, …). An adjacent skill gets partial credit in the `skills` component and shows as "adjacent", not "missing". | The steps above, on `rescore` and the chosen rerank variant. The change in `missing` count over the 1,000 pairs. The full dictionary is printed in the report. Whether adjacency helps is decided by the judged metrics, not by hand review. |
| B2 | **Posting signals** (was "ghost job"; hireplz) | **No "ghost job" label or claim.** Factual signals computed at read time: age, repost count (same role fingerprint), number of sources, identical concurrent openings, evergreen wording. They are shown on the card as facts ("Posted 11 months ago · reposted 3 times · seen at 2 sources"). | Display needs no metric. Any ranking use (for example, demoting a posting where 2 or more signals fire) is measured by NDCG@10 and MRR like the others (configurations 2 and 12). It is combined with B1 so old ATS requisitions are not penalised twice. |
| B5 | **Natural-language search intent** (hireplz) | "backend fresher in Bengaluru" becomes structured filters through schema-validated LLM output. The call is `data_class` personal when the profile is included, so it goes Groq → Ollama and **never Gemini**. Decoding is tolerant. Contradictions are shown to the user, not guessed. | **Answers known by construction:** 50 queries generated from templates with known filters (for example, "remote data engineer jobs in India paying over 15 LPA" → `{workplace: remote, role: data engineer, country: IN, salary_min: 15 LPA}`), plus 10 messy hand-written variations. **These 10 are not known by construction:** their expected filters are a written reference (drafted by Claude, read by the owner), reported separately and labelled that way. The report gives the field-level exact-match rate (templated queries: answers known by construction; messy: against the written reference; reported separately), plus query mode with parsed filters vs raw query on the 25 profiles (the steps above) and latency p50/p95. |

### Not in 5b

- **Dedup keeps the newest posting** (Phase 4 backlog): this is an ingest change, which
  needs a dry run and a migration note. I propose a separate small PR after 5b.
- **Liveness probe**: Phase 9 (System page).

---

## Owner decisions (2026-11-27)

1. Resume parsing and stored profiles become 5c, after Docker is free. Until then the
   profile lives in `localStorage` with a "Clear my data" button.
2. About 12 fictional postings, covering the edge-case table above.
3. No MSW.
4. Vitest, Testing Library and axe-core as a step inside the existing frontend CI job.
5. The 5b order is B1 → B3 → B4 → B2 → B5, with **B0 first** (added 2026-11-28 from PR #6).
6. No human labelling. B2 reports facts, not a "ghost job" claim. B3 is measured as
   agreement with an LLM or mechanical reference. B5's answers are known by
   construction.
7. Added to 5a: Save / Not for me with a reason, the salary display rules, the snippet
   note, the structured-first "why it matches", and the font choice.
8. Process: build the list and the card first, send screenshots (360 px and 1280 px,
   light theme, one ruled-out and one snippet example visible), then stop for review.
