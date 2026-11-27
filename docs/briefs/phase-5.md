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
| Posted more than 365 days ago | "Posted 14 months ago" |
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

### Checks

- `npm run lint`, `typecheck`, `build` and `test`. Vitest, Testing Library and axe-core
  run as a step inside the existing `Frontend (lint, types, build, audit)` CI job. No job
  is renamed or added.
- Component tests on the test data cover every edge case in the table above, the
  feedback round-trip through `localStorage`, and an axe check per state.
- Screenshots at 360 px and 1280 px.

---

## 5b: Ranking changes (after Phase 4 merges)

### How every item is measured

These steps are the same for every item:

1. Add the change as a **new named variant** behind a config flag (default off). Run it
   on the frozen snapshot `2026-11-25` in `query` and `profile` mode, and append its
   rankings to `runs.jsonl`.
2. Use `make eval-fill` so every top-10 job of the new variant has a grade. Judge the new
   pairs with the same rubric (`eval_judge/v1`, Gemini primary, `data_class` public,
   fictional profiles), and report how many pairs were added so pool bias is visible.
3. Use `make eval FULL=1` to report NDCG@10, MRR and Recall@30 with 95% bootstrap CIs
   over the 25 profiles. Include a paired test against the current production variant,
   on all pairs and on the **posted within 90 days** subset.
4. Run the robustness check (§7 of the Phase 4 report): does the change hold under Groq,
   Cowork and the 3-judge majority on the blind pairs?
5. Apply the decision rule: switch the flag on only if NDCG@10 does not drop on either
   subset (CI overlap counts as no drop) **and** the item's own check below passes. Then
   re-measure `gate/baseline.json`, give the reason in the decision log, and let the CI
   gate guard it.
6. Before each run that uses more than 5 minutes of full CPU, state the runtime
   estimate. Measure Gemini quota use per batch.

All grades are LLM-judged, and every table says so.

### Items, in order

| # | Item | What changes | Measured by (beyond steps 1–5) |
|---|---|---|---|
| B1 | **Freshness / stale filter** (Phase 4 backlog) | Demote postings more than 90 days old. Hide postings more than 365 days old unless `is_evergreen`. The age display is already in 5a. | Main metrics on the within-90-days subset vs all pairs. Count of judged-relevant pairs (grade 2 or more) that the 365-day hide removes, listed in the report as its cost. Today 103 of the 1,000 pairs are more than 365 days old. |
| B3 | **Requirement blockers** (hireplz). Early, because the Phase 4 truncation check showed that experience mismatch drives grades. | From each JD: minimum years, degree, language, work authorisation, location or work mode, certification. Rules run first, with LLM fallback (`data_class` public, JD text only). Each blocker is graded hard, medium or soft, then met or unmet against the profile. An unmet hard blocker caps the fit label at "Stretch" and appears in `Explanation`. | **Agreement with an LLM reference, never called human-validated.** (a) Mechanical ground truth for years of experience and degree: deterministic regexes over the JD text, reported as precision and recall of the extractor against them. (b) Gemini extraction on public JD text for the other types, with agreement per type. (c) Cowork spot-checks a stratified sample of (b) as an LLM judge, and its agreement is reported. On eval pairs: the judge grade distribution for jobs with an unmet hard blocker, then steps 1–5 for the demotion variant. |
| B4 | **Skill adjacency** (hireplz) | A curated dictionary of substitutable skills (pytorch↔tensorflow, postgresql↔mysql, aws↔gcp↔azure, react↔vue↔angular, kafka↔rabbitmq, …). An adjacent skill gets partial credit in the `skills` component and shows as "adjacent", not "missing". | Steps 1–5 on `rescore` and the chosen rerank variant. The change in `missing` count over the 1,000 pairs. The full dictionary is printed in the report. Whether adjacency helps is decided by the judged metrics, not by hand review. |
| B2 | **Posting signals** (was "ghost job"; hireplz) | **No "ghost job" label or claim.** Factual signals computed at read time: age, repost count (same role fingerprint), number of sources, identical concurrent openings, evergreen wording. They are shown on the card as facts ("Posted 14 months ago · reposted 3 times · seen at 2 sources"). | Display needs no metric. Any ranking use (for example, demoting a posting where 2 or more signals fire) is a variant measured by NDCG@10 and MRR in steps 1–5, like the others. It is combined with B1 so old ATS requisitions are not penalised twice. |
| B5 | **Natural-language search intent** (hireplz) | "backend fresher in Bengaluru" becomes structured filters through schema-validated LLM output. The call is `data_class` personal when the profile is included, so it goes Groq → Ollama and **never Gemini**. Decoding is tolerant. Contradictions are shown to the user, not guessed. | **Ground truth by construction:** 50 queries generated from templates with known filters (for example, "remote data engineer jobs in India paying over 15 LPA" → `{workplace: remote, role: data engineer, country: IN, salary_min: 15 LPA}`), plus 10 messy hand-written variations whose expected filters I write and the owner checks by reading. The report gives field-level exact-match accuracy (templated and messy reported separately), plus query mode with parsed filters vs raw query on the 25 profiles (steps 1–5) and latency p50/p95. |

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
5. The 5b order is B1 → B3 → B4 → B2 → B5.
6. No human labelling. B2 reports facts, not a "ghost job" claim. B3 is measured as
   agreement with an LLM or mechanical reference. B5's ground truth comes from
   construction.
7. Added to 5a: Save / Not for me with a reason, the salary display rules, the snippet
   note, the structured-first "why it matches", and the font choice.
8. Process: build the list and the card first, send screenshots (360 px and 1280 px,
   light theme, one ruled-out and one snippet example visible), then stop for review.
