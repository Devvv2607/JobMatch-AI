# Backlog: ideas borrowed from hireplz

Recorded 2026-11-24 from the owner's notes. Documentation only: each item is built in the
phase named in brackets, as part of that phase's brief.

## Context

hireplz (MIT licence, <https://github.com/nishant-Tiwari24/hireplz>) is a large
India-first job platform that overlaps with JobMatch. We do not compete on breadth. Our
edge is **measured relevance, explainable ranking, verified "never invent" tailoring, and
an evaluated agent and voice interview**. Borrow only ideas that strengthen those or our
India coverage.

Rules for borrowing:

- When porting logic, credit hireplz (MIT) in a code comment at the ported code and in
  the README.
- Never copy their scraping-based adapters (LinkedIn, Naukri, Wellfound and the like).
  JobMatch uses official feeds and public ATS endpoints only.

## Items by target phase

### Phase 2b (more sources)

- **Lexical near-duplicate detection.** Within a (company, normalised title) bucket,
  word-set overlap ≥ 0.9 on boilerplate-stripped text = the same posting; skip buckets of
  more than 200 postings. Keep the earliest as canonical; the others get `duplicate_of`
  and appear as "also posted in X". Validate on 50 hand-checked pairs and report
  precision. Replaces the disabled embedding near-duplicate pass.
- **Indian ATS adapters: Keka, Darwinbox, greytHR.** Check each one's public careers
  endpoint and terms first; build only where allowed; log the decision.
- **Board discovery via the Common Crawl URL index** (free) for Greenhouse, Lever, Ashby,
  SmartRecruiters, Keka and Darwinbox board URLs; verify each board live; rate-limit
  politely.
- **Deterministic salary extraction with refusal rules**, including Indian formats (LPA,
  lakh, crore, ₹, INR, CTC). Refuse ambiguous text (mixed periods, scaled or half-read
  amounts) rather than guess. Precedence: ATS structured salary > parsed text. Unit tests
  from real postings.

### Phase 5 (resume and profile)

- **Requirement blockers** extracted from each JD (rules first, LLM fallback,
  `data_class=public`): minimum years, degree, language, work authorisation,
  location/work mode, certification. Each graded hard / medium / soft and met / unmet
  against the profile, shown in the explanation object. An unmet hard blocker caps the
  fit label at "Stretch".
- **Skill adjacency:** a small curated dictionary of genuinely substitutable skills
  (pytorch↔tensorflow, postgresql↔mysql, aws↔gcp↔azure, react↔vue↔angular,
  kafka↔rabbitmq, …). A missing skill with an adjacent one in the profile reads as
  "adjacent" (partial credit, explained), not "missing".
- **Ghost-job signal**, computed at read time, not stored. Structural signals: posted
  ≥ 90 days ago, reposted ≥ 3 times (same role fingerprint), ≥ 5 concurrent identical
  openings, evergreen wording ("always hiring", "talent pool"). Needs ≥ 2 signals for
  "possible"; show which fired; never "likely" from structural signals alone.
  Inputs that already exist (2026-11-26): `stale_posting` (the posting's own date over
  365 days old; search already ranks these after fresher results and says "posted over
  a year ago"), `openings_count` (concurrent identical openings), `is_evergreen`. On the
  2026-11-25 snapshot, 2,342 of 23,705 searchable jobs were over a year old (Adzuna 755
  of 1,470, Greenhouse 1,289 of 9,906) and 6,245 over 90 days. An ATS board lists only
  open jobs, so an old date there means a long-open requisition, not a closed one: weigh
  age by source (aggregator vs ats_direct).
- **Natural-language search intent:** "backend fresher in Bengaluru" → structured filters
  via schema-validated LLM output (`data_class=personal` when the profile is included),
  tolerant decoding (a scalar where a list is expected), contradictions shown to the
  user, not guessed. Eval on 50 labelled queries, field-level accuracy.

### Phase 5 / 9

- **Liveness probe and weekly quality audit:** sample N served postings, GET the source
  URL (respect robots.txt and rate limits); 404/410 = dead; transport errors =
  unmeasured, never counted as live. Publish "% verified live" on the System page and in
  the README.

### Phase 6 (tailoring and verifier)

- **Experience bank with provenance:** each claim labelled `cv_import` / `manual` /
  `stated_in_chat` / `agent_inferred`, the label derived from the entry point, never from
  the request body. Only the first three may appear in a tailored resume;
  `agent_inferred` needs explicit user confirmation; unknown labels fail closed. The
  verifier treats the bank as source evidence. Test the laundering case (editing an
  inferred claim keeps it inferred).

### Phase 7 (career agent)

- **MCP server** (Python, official SDK or FastMCP): tools `search_jobs`, `explain_match`,
  `get_job`, `list_saved`; read-only by default; per-user API key; rate-limited; README
  with a Claude Desktop config example.

### Phase 9 (tracker, readiness, system)

- **Saved searches and alerts** via a Telegram bot (free) and optional email, built on the
  daily digest, with unsubscribe and quiet hours.
- **Market signals on Readiness:** a skill's share of the target role's live postings,
  with month-over-month change.

### Phase 10 (hardening and deploy)

- **Repo hygiene:** a short `AGENTS.md` per backend module stating its invariants; a
  diff-cover gate (coverage on changed lines); a CI performance budget for search p95;
  CodeQL and OSV scanning.

## Out of scope

See [docs/out-of-scope.md](../out-of-scope.md).
