# Phase 2b: More job sources (official feeds only)
Branch phase-2b-sources. Starts after 3b merges, finishes before Phase 4. No HN
"Who is hiring" here (it needs about 1,000 LLM calls; it comes after Phase 4).

1. YC companies. Never access ycombinator.com or workatastartup.com programmatically
   (their terms prohibit scraping). Download
   https://yc-oss.github.io/api/companies/hiring.json (open yc-oss dataset) at most
   weekly, cached; use only name, website, batch, industry, regions and remote fields.
   Detect a Greenhouse / Lever / Ashby / SmartRecruiters board per company (slug
   variants against public endpoints, then the careers link on the company's own site:
   one request per site, respecting robots.txt). Verify each board returns jobs.
   Prioritise India-hiring and remote-friendly companies. Add verified boards to
   companies.yaml with yc_batch, industry, source=yc-oss.
2. VC portfolio companies (Peak XV, Accel, Lightspeed, a16z, Sequoia, Elevation,
   Blume). Check each portfolio page's terms first; use only pages that allow automated
   access, otherwise skip and log why. Same board detection, tagged with investors.
3. New source adapters (same normalise → dedup → embed pipeline):
   - Himalayas remote jobs API (free, no auth): reasonable request volume, back off on
     429, show "Source: Himalayas" with a link, never resubmit their jobs to third-party
     sites. Parse timezone/country restrictions into work eligibility.
   - SmartRecruiters public Posting API: one adapter, plus companies in companies.yaml
     (India-hiring first, each verified).
   - Adzuna API (free key; I'll add ADZUNA_APP_ID / ADZUNA_APP_KEY to .env), country=in
     plus remote queries. Track monthly usage in Redis and stop at 80% of the free quota.
     Descriptions are often truncated: set description_quality="snippet".
   - Workable / Recruitee: check public endpoints and terms first; build only if both
     allow it, otherwise log why.
   - Never: LinkedIn, Indeed, Glassdoor, Internshala or Naukri scraping, or web-search
     "jobs". The README states which portals aren't covered and why.
4. Cross-source dedup: same company + normalised title + location (plus description
   similarity) across sources = one job. Keep the company's own ATS posting as the main
   record and store others as alternate_sources. Tests.
5. source_quality field: ats_direct / aggregator_full / aggregator_snippet (Phase 4
   tests whether it should affect ranking).
6. startup_backed filter rule (YC or VC-backed), as a new dealbreaker rule class, with
   tests and ruled-out labelling.
7. README attribution: "YC company list from the open yc-oss dataset; job data from
   each company's public ATS board, Himalayas, Adzuna and Remotive APIs."
8. Lexical near-duplicate detection (from [backlog-from-hireplz.md](backlog-from-hireplz.md)):
   within a (company, normalised title) bucket, word-set overlap ≥ 0.9 on
   boilerplate-stripped text = same posting; skip buckets over 200 postings. Keep the
   earliest as canonical; others get duplicate_of and appear as "also posted in X".
   Validate on 50 hand-checked pairs and report precision. Replaces the disabled
   embedding near-dup.
9. Indian ATS adapters: Keka, Darwinbox, greytHR. Check each one's public careers
   endpoint and terms first; build only where allowed; log the decision.
10. Board discovery via the Common Crawl URL index (free) for Greenhouse, Lever, Ashby,
    SmartRecruiters, Keka and Darwinbox board URLs; verify each board live; rate-limit
    politely.
11. Deterministic salary extraction with refusal rules, incl. Indian formats (LPA,
    lakh, crore, ₹, INR, CTC). Refuse ambiguous text (mixed periods, scaled or
    half-read amounts) rather than guess. Precedence: ATS structured salary > parsed
    text. Unit tests from real postings.
12. Run the ingest (disk check and backup first; tell me before long full-CPU runs).
   Report per source: companies discovered → boards found → verified; jobs added;
   India eligible / unknown / ineligible; remote-eligible; cross-source duplicates
   merged; failures with reasons; embed time; peak memory.
9. PR, CI green, evidence, STOP.
