# Phase 5c: Resume parsing and stored profiles

- Drafted 2026-11-28 and revised the same day with the owner's decisions (§10).
- Branch `phase-5c-profile`.
- **Built after Phase 4 merges**, because it needs Docker.

5c turns the 5a profile, which lives in the browser, into an account profile stored on
the server. That profile can come from a parsed resume, and every parsed fact links back
to the place in the resume it came from. It also ships the backend changes queued in 5a.

Sources:
- [PLAN.md](../../PLAN.md) §2.2 (resume engine) and §3 (schema).
- [ADR 0001](../decisions/0001-llm-data-routing.md) (LLM routing by data class).
- [phase-5.md](phase-5.md) (5a decisions and the API gaps list).
- The 25 fictional eval profiles (`eval/profiles/p01–p25.yaml`, on `phase-4-eval` until
  Phase 4 merges).

**Ground rules for the whole phase**

- **No human labelling.**
  - Extraction quality is measured on synthetic resumes whose ground truth is known
    because we generate them (§7).
  - The cost of parsing errors on matching is measured with the Phase 4 harness and its
    LLM judge (§7.3).
- **No real resume in git:** not in commits, fixtures, test data or screenshots.
  - Synthetic resumes only.
  - The owner's real resume stays in `eval/private/`, which is gitignored.
- **Personal data never goes to Gemini** (ADR 0001).
  - Resume text, parsed fields and anything derived from them are `personal`: Groq,
    then Ollama on this machine.
  - The user can narrow this further, to this server only (§4).
- **Resume text is untrusted data.** It can never act as instructions (§2.2).
- **Free tools only.** Every library below is free and open source. No paid OCR or
  parsing APIs.
- **Nothing is auto-trusted.** Parsed fields are suggestions until the user confirms them
  (§3).

---

## 1. Parsing pipeline

```
POST /resumes ─ checks (§2.1) ─ encrypted file saved ─ arq job enqueued ─▶ 202 {task_id}
worker:  queued → extracting → reviewing  (or → failed, with a reason code)
         extracting = text extraction with offsets → hidden-text scan (§2.2) → rules
                      → redaction (§1.4) → LLM extraction, if the user allows (§4)
                      → span validation (§3)
user:    reviews and confirms → candidate_profiles + resume_spans   (parse: confirmed)
```

### 1.1 Background job and progress states

- **Parsing runs as an arq job in the worker, never inside the request.**
  - The upload returns `202` with a task id.
  - The UI polls `GET /api/v1/resumes/{id}/parse`, using the existing
    `background_tasks` pattern.
- **States the user sees:**

  | State | Meaning | Shown as |
  |---|---|---|
  | `queued` | Waiting for the worker | "Waiting to start…" |
  | `extracting` | Reading text, rules, LLM | "Reading your resume…" (with the step: text, details) |
  | `reviewing` | Done; waiting for the user to check it | The review screen |
  | `failed` | Stopped, with a reason code (§8) | The plain message for that reason |
  | `confirmed` | The user saved the profile | Back to the profile page |

- **Job limits:**
  - The job times out after 120 seconds (text extraction plus at most one local LLM
    call; see §1.5).
  - One parse per user at a time; a new upload cancels the queued one.
  - If the worker restarts, a job stuck in `extracting` for 10 minutes becomes `failed`
    with `worker_restart`, and the user can retry.

### 1.2 Text extraction (local, free)

| Format | Library (licence) | What we keep |
|---|---|---|
| PDF | `pdfplumber` on `pdfminer.six` (MIT) | Characters with positions, font size and fill colour, grouped into words and lines. The output is one plain-text string plus a map from each character back to its page and bounding box. |
| DOCX | `python-docx` (MIT), with XML parsed through `defusedxml` | Paragraphs and table cells in document order, with each run's formatting (hidden, colour, size), as one plain-text string. |

- **Not PyMuPDF.** Its AGPL licence is a poor fit for this repo.
- **Columns:** words are grouped into columns by gaps in their x-positions, then each
  column is read top to bottom. A two-column resume must not interleave its lines. This
  is measured on two-column synthetic resumes (§7).
- **One canonical text string per resume.** Spans are offsets into it, and it never
  changes after the parse.
- **Limits** (owner decision): 5 MB and **at most 10 pages**. Also at most 60,000
  characters of extracted text. Anything over a limit fails with a clear message (§8).

### 1.3 Deterministic extraction first

Rules handle everything they can, and each rule records the span it matched:

| Field | Rule |
|---|---|
| Email, phone, URLs | Regex. Used **only for redaction** (§1.4); never stored in the profile. |
| Candidate name | The heading lines before the contact block: 2 to 4 capitalised words with no digits, on the first lines of page 1 or in the DOCX title or heading style. Used **only for redaction**. |
| Section boundaries | Headings matched against a list ("Experience", "Work history", "Education", "Skills", "Projects"…), using case and line position. |
| Date ranges | Regex for "Jan 2022 – Present", "2019–2021", "03/2020 - 08/2023" and similar. "Present" or "Current" means the upload date. |
| Years of experience | Merge the date ranges in the Experience section, counting overlapping periods once, and sum them. Internships are counted separately, so the user can choose whether to include them. |
| Skills | The existing taxonomy matcher (`app/ingest/skills.py`) returns each match with its span. |
| Degree | Patterns such as B.Tech, B.E., BSc, MSc, M.Tech, MBA, PhD, "Bachelor of…", plus a graduation year. |
| Level (suggested) | The existing title rules (`app/ingest/seniority.py`) applied to the most recent title, then checked against the years of experience using the `EXPECTED_YEARS` bands. |

### 1.4 Redaction before any LLM call

- **What gets replaced:** the candidate's name, email, phone and URLs, everywhere they
  appear (not only in the header).
- **How:** each is replaced with a placeholder of the same length (for example
  `[NAME···]` padded), so offsets in the LLM's answer still point at the right place in
  the stored text.
- **If the name can't be found:** the user is told before the LLM step ("We couldn't find
  your name to hide it. Continue, or parse on this server only?").
- **Hidden text** found by §2.2 is blanked out the same way, so the LLM never reads it.
- **Tests:** in the synthetic set, the planted names and contact details reaching the LLM
  must be **0**. The test captures the exact prompt the client would send.

### 1.5 LLM extraction, only for what rules can't do

- **What the LLM handles:**
  - Job titles and employers.
  - Skills that aren't in the taxonomy.
  - The education institution.
  - **Field**, from a fixed list (owner decision): the existing field taxonomy
    `ml_ai`, `data`, `backend`, `full_stack`, `product_analyst`, plus "Other (free
    text)". The 5a free-text "Field" input becomes this select.
  - A level, when the rules disagree with each other or find nothing.
- **Providers follow the user's choice** (§4) inside the ADR 0001 policy:
  - **Groq (fast):** Groq first, Ollama as fallback.
  - **This server only:** Ollama only.
  - Never Gemini in either case.
  - With no allowed provider available, the parse ends with the rule-based fields and
    says the rest needs filling in by hand.
- **Constrained output:**
  - JSON schema mode (Groq `response_format: json_schema`, Ollama `format` with the
    schema), then validation into a Pydantic `ParsedResume`, with the existing bounded
    repair step.
  - Enum fields (field, level) accept only listed values.
  - Each item is `{value, quote, start, end, confidence}`.
- **No LLM cache for resume calls.** A cached row would hold personal output.

### 1.6 Local model: 3B only (owner decision)

- **Machine:** Ryzen 7 7445HS, 12 threads, 15 GB RAM, CPU only. A 7B model is ruled out
  for RAM.
- **Estimates, not measurements** (CPU-only, Q4):

  | Model (Q4, Ollama) | Disk | RAM while running | One resume (≈3k tokens in, ≈800 out) |
  |---|---|---|---|
  | `llama3.2:3b` (current `OLLAMA_MODEL` default) | ≈2.0 GB | ≈3 GB | ≈40–90 s |
  | `qwen2.5:3b` | ≈1.9 GB | ≈3 GB | ≈40–90 s |

- **Pilot, before choosing:**
  - Both models parse the same 6 synthetic resumes: 3 layouts × 2 profiles, plus 2
    attack resumes from §7.
  - **Runtime estimate: about 15–20 minutes of full CPU.** It needs the owner's OK
    before it starts.
  - Models run one at a time (`OLLAMA_MAX_LOADED_MODELS=1`, unloaded in between), and
    peak RAM is recorded.
  - Compared on field accuracy (§7.2 metrics), JSON validity (share valid on the first
    try, and after repair), injection resistance, and time per resume.
  - The model is picked on those measured results, and the choice goes in the decision
    log with the numbers.

## 2. Security

### 2.1 Files

- **Type sniffed from the bytes, never the extension or `Content-Type`:**
  - PDF must start with `%PDF-`.
  - DOCX must be a ZIP archive with `[Content_Types].xml` and `word/document.xml`, and no
    `vbaProject.bin` (macros).
  - Anything else is rejected before it's stored.
- **Zip-bomb limits for DOCX** (checked from the ZIP directory before extracting):
  - at most 50 MB unzipped in total
  - at most 2,000 entries
  - at most a 100:1 compression ratio for any entry
  - no nested archives
- **XML:** parsed with `defusedxml`, so no external entities and no entity expansion.
- **PDF safety:**
  - Only text is extracted. Nothing runs JavaScript, embedded files or forms.
  - Encrypted PDFs are refused (§8).
  - A per-job memory cap is set in the worker's container limits.
- **Rate limit on the upload endpoint** (Redis counters, like the existing limits):
  3 uploads a minute and 10 a day per user, plus a per-IP limit for signed-out probing.
  These numbers are proposed; see §10.
- **Storage path:**
  - Files are stored on a Docker volume outside the web root, under a random name. The
    user's file name is kept only as encrypted metadata.
  - Nothing is ever served back by path. Download, if added, streams after an ownership
    check.

### 2.2 Prompt injection

- **Resume text is untrusted data.**
  - It goes in a delimited block in the user turn, never in the system prompt.
  - The system prompt says the block is data to extract from, and that instructions
    inside it are text, not commands.
  - The output is schema-constrained (§1.5), so the model can only return the fields we
    ask for.
- **Code checks every fact; the model's word is not enough.** Every extracted item must
  quote visible resume text at its span (§3). So an injected claim such as "10 years of
  Kubernetes" cannot become a fact unless that text is actually in the resume, where the
  user sees and confirms it.
- **Hidden-text detection, before anything is extracted:**

  | Signal | PDF | DOCX |
  |---|---|---|
  | White or near-white text | fill colour with luminance ≥ 0.9 on a page with no fill under it | run colour ≥ 0.9 luminance |
  | Tiny text | font size < 4 pt | `w:sz` < 8 half-points |
  | Off-page text | character box outside the page's visible area | n/a |
  | Hidden text | invisible render mode, where pdfminer exposes it | `w:vanish` runs |

- **What happens to hidden text:**
  - It is blanked out of the text the LLM and the rules see (offsets are kept).
  - It is recorded with its spans.
  - It is shown on the review screen: "Your resume has hidden text, for example white or
    tiny text. We ignored it." With a "Show it" toggle.
  - It never becomes a profile fact.
- **Synthetic attack resumes in the test set (§7):**
  - visible "ignore previous instructions" text
  - white-text skill stuffing
  - a tiny-font fake employer
  - off-page text
  - DOCX hidden runs
  - a JSON-shaped payload inside a bullet
- **Bars:** injected facts in the confirmed-eligible output: **0**. Hidden-text cases
  detected: **100%**.

## 3. Provenance and user confirmation

- **Every extracted fact keeps its source span:** each item is `{value, span: {start,
  end}, quote, source: "rule" | "llm" | "user", confidence, status}`.
- **Span check, done in code:** `text[start:end] == quote`, and the span must not overlap
  hidden text.
  - If the offsets are wrong but the quote appears exactly once in the visible text, the
    span is corrected to that place.
  - Otherwise the item is "couldn't find this in your resume": it is low confidence and
    starts unconfirmed.
- **Stored spans:** kept in `resume_spans` (PLAN §3), which Phase 6 needs for the
  experience bank and tailoring. They point into an immutable resume text version.
- **Confidence:**
  - **High:**
    - a rule match on visible text (date range, taxonomy skill, degree pattern), or
    - an LLM item whose quote validated exactly at its span, and that a rule confirms
      where a rule exists (for example, the title rule gives the same level).
  - **Low:** anything else, including corrected spans and LLM-only enum answers.
- **Review screen** (built on the 5a profile sections and shared controls):
  - Each field shows its value and the highlighted snippet it came from.
  - **"Confirm all" applies only to the high-confidence fields** (owner decision).
    Low-confidence fields are confirmed, edited or removed one by one, and saving stays
    disabled until each has been handled.
  - The screen says how many fields are in each group.
- **Nothing is saved to `candidate_profiles` until the user confirms.**
  - The parse result waits as `reviewing` and is deleted after 7 days unconfirmed.
  - An edited field keeps its original span, and its source becomes `user`.
  - A field the user adds by hand has no span.
- **Matching and tailoring use confirmed facts only.**

## 4. Consent to parse with an LLM

- **The first time someone uploads, they choose:**
  - **Parse with Groq (fast).** "Your resume text is sent to Groq, with your name and
    contact details hidden. Groq doesn't keep it."
  - **Parse on this server only (slower).** "Nothing leaves this server. Takes a minute
    or two."
- **There is no default:** the upload button asks until a choice is made.
- **The choice is remembered** in the user's settings (`parse_provider`: `groq` |
  `local`) and can be changed on the profile page.
- **Under "this server only", Groq is never called**, even when Ollama is unavailable.
  The parse then ends with the rule-based fields.
- **This narrows ADR 0001 per user and never widens it:**
  - Gemini is never allowed whatever the setting.
  - A test checks that `local` users' parses never reach the Groq adapter. It uses the
    same send-path guard as the ADR tests.
- **The privacy note on the upload screen** says what each option sends and keeps, in
  two lines.

## 5. Storage, privacy and retention

### 5.1 What is stored

| Data | Stored | Where | Retention |
|---|---|---|---|
| Original file (PDF/DOCX) | Yes, encrypted, **latest only** (owner decision) | Volume outside the web root | Replaced when a new resume is uploaded. Deletable any time ("Delete my original file"). Deleted right after parsing if the user ticks "Delete the original after parsing" (remembered). Phase 6 tailoring edits this file, so it is kept by default. |
| Extracted canonical text | Yes, encrypted, latest only | `resumes.text_encrypted` | Replaced with the file; deleted on delete-my-data |
| Parse result awaiting review | Yes, encrypted | `resume_parses` | 7 days unconfirmed, then deleted |
| Confirmed profile | Yes | `candidate_profiles`: encrypted JSONB for items and spans; plain columns for what search filters on (skills, years, preferences, field) | Until deleted, or 12 months of inactivity (§5.4) |
| Resume spans | Yes, encrypted text | `resume_spans` | Follow the resume |
| Hidden-text findings | Yes, spans only | `resume_parses` | Follow the parse |
| Dealbreakers, feedback, consent choice | Yes | `dealbreakers`, `job_feedback`, user settings | Until deleted |
| Name, email, phone, URLs | **No** (detected for redaction only) | n/a | Never stored as fields; they remain inside the original file and text the user uploaded |

### 5.2 Encryption at rest

- **Application-level AES-256-GCM** with the `cryptography` package (Apache-2.0/BSD).
  - Applies to the file, the resume text, parse results, items and spans.
  - The key comes from `PROFILE_ENCRYPTION_KEY` in `.env`. The owner creates it; it is
    never printed or committed.
  - Each ciphertext records which key encrypted it, and a re-encrypt command rotates
    keys.
- **Search columns stay in plain text**, because the SQL filters on them.
- **Disk encryption (BitLocker) is the host's job.** The README says so.

### 5.3 Logs and traces

- **Logs:**
  - The JSON logger gets a redaction filter for emails, phones and tokens.
  - Personal LLM calls log only the request id, provider, model, token counts, latency
    and status, never the prompt or response.
  - A test runs a synthetic resume through the pipeline and asserts none of its text,
    name or contact details appear in the captured logs.
- **Langfuse** (behind `--profile tracing`, off by default):
  - Personal inputs and outputs go through the masking hook and become
    `[personal: N chars]`.
  - Traces carry a hashed user id, so deletion can find them.
- **Errors:** parser exceptions never include document text.

### 5.4 Deletion and the inactivity cleanup

- **"Delete my data"** (`DELETE /api/v1/me/data`) and **account deletion** remove:
  - the file and its text
  - parses, spans (and Phase 6 embeddings), the profile, dealbreakers, feedback and
    digests
  - consent settings
  - the user's Redis keys, queued arq jobs, task rows and Langfuse traces
- **The test proves it:** it finds every table with a `user_id` column, fills each,
  deletes, and asserts zero rows remain, plus no files and no Redis keys. A user-owned
  table added later fails it until deletion covers it.
- **"Clear my data" in the frontend** (5a) calls this endpoint when signed in, and says
  what it removed.
- **Inactive accounts are deleted after 12 months** (owner decision):
  - "Activity" is a successful sign-in or token refresh (`users.last_active_at`).
  - A daily arq cron deletes accounts inactive for more than 365 days, using the same
    deletion function.
  - It is tested with a frozen clock: 364 days kept, 366 deleted, everything gone.
  - The policy is stated on the profile page and in `docs/privacy.md`.
  - The app sends no email, so there is no warning before deletion. The page says so.

### 5.5 No real resumes in the repo

- **Synthetic resumes** live in `eval/synthetic_resumes/`, generated by a committed
  script and stamped with a marker in their metadata.
- **CI guard, a new step inside the existing backend job** (no new or renamed job): it
  fails if a `.pdf` or `.docx` is committed outside that folder, if a file there lacks
  the marker, or if anything under `eval/private/` is tracked.

## 6. Accounts and migration

- **Reuse the Phase 1 auth unchanged:**
  - Argon2 passwords.
  - Access token kept in memory.
  - Rotating refresh cookie with reuse detection.
  - The CSRF header.
- **That is the minimum needed:** every new endpoint needs a signed-in user, and every
  row is scoped by `user_id`. No email verification or password reset in 5c; they go to
  the backlog.
- **Endpoints:**
  - `POST /api/v1/resumes`
  - `GET /api/v1/resumes/{id}/parse`
  - `POST /api/v1/resumes/{id}/confirm`
  - `DELETE /api/v1/resumes/original`
  - `GET` and `PUT /api/v1/profile` (the 5a `StoredProfile` shape)
  - `GET` and `PUT /api/v1/dealbreakers`
  - `POST` and `DELETE /api/v1/feedback`
  - `GET` and `PUT /api/v1/me/settings` (consent, keep-original choice)
  - `DELETE /api/v1/me/data`
- **Search reads the stored profile** when the request carries none, as PLAN.md planned.
  An explicit profile still works, for the eval harness.
- **Migrating the browser profile into an account (one-off, on sign-in):**
  - Browser profile present, account has none: offer to save it to the account. The
    browser copy is removed after the server confirms.
  - Both present and different: show both summaries and let the user choose. Never merge
    silently.
  - Saved and hidden jobs move the same way, resolved by `job_id`, keeping the newest.
  - The browser data is validated with the API's schema. If the upload fails, the browser
    copy is kept.

## 7. Evaluation without human labels

### 7.1 Synthetic resumes, with ground truth by construction

- **A generator turns each of the 25 eval profiles into resumes.**
  - Each persona, field, experience band and skill list becomes made-up names, employers,
    titles, date ranges, education and bullets.
  - It uses templates and seeded random choices, with **no LLM for the facts**.
  - It records every fact's exact span as it writes the document.
- **Layouts:** each profile is rendered in at least 2 of the following, giving 50+
  documents:
  - single-column PDF
  - two-column PDF
  - DOCX with tables
  - dense PDF with no headings
  - Rendering uses `reportlab` (BSD) and `python-docx` (MIT).
- **Extra documents:**
  - the attack set (§2.2)
  - the failure set (§8)
  - a few with overlapping jobs and internships, to test the years arithmetic
- **Parsed as personal, even though they are fictional.** They run through exactly the
  production path, with redaction, consent routing and no cache, so the eval measures
  what users get.

### 7.2 Field-level extraction accuracy

- **Goals, reported against what was measured** (owner decision). Every row is reported
  for **Groq** and **Ollama (the chosen 3B)** separately, plus **rules only**, and split
  by layout:

  | Field | Metric | Goal |
  |---|---|---|
  | Provenance | items whose quote is at their span (in visible text) | 100% |
  | Dates and years | date ranges exact; total years within ±0.5 | ≥ 95% |
  | Skills | precision and recall vs the profile's canonical skill set | ≥ 90% each |
  | Titles and employers | exact match after case and whitespace normalisation | ≥ 90% |
  | Level | match with the profile's seniority | ≥ 85% |
  | Field | exact match with the profile's field | ≥ 85% |
  | Education | degree level, institution and year, each exact | reported (no goal set) |
  | Redaction | planted names and contacts reaching the LLM | 0 |
  | Injection | injected facts in confirmed-eligible output; hidden text detected | 0; 100% |
  | JSON validity | valid on the first try; valid after repair | reported |

- **Wording:** "agreement with constructed ground truth on synthetic resumes". A missed
  goal is reported as missed, with the failing cases listed, never re-labelled.
  Synthetic layouts are cleaner than real ones, and the report says so.

### 7.3 Downstream: what parsing errors cost in matches

- **For each synthetic resume, the Phase 4 harness runs two searches** on the frozen
  snapshot (2026-11-25):
  - one with the **true profile** (the eval yaml)
  - one with the **parsed profile** (what the user would confirm if they accepted every
    suggestion)
  - Both use the profile's true dealbreakers and query, so only the parsed fields
    differ.
- **Reported, per provider:**
  - **NDCG@10** for both, and the paired difference (parsed − true) with a bootstrap 95%
    CI, using the Phase 4 judge labels.
  - **Top-10 overlap:** |parsed ∩ true| / 10, as a mean and distribution.
  - **Where the cost comes from:** the drop in NDCG@10 is regressed on each field's
    error. For example: does missing two skills or being off by a year matter more?
- **Unjudged pairs:**
  - Parsed profiles can surface jobs the Phase 4 pool never judged.
  - The report gives judged coverage of each top 10.
  - Unjudged pairs are judged with the Phase 4 judge (`make eval-fill`, rubric
    `eval_judge/v1`). That is allowed under ADR 0001 because the profiles and postings
    are fictional and public. The quota and runtime estimate are given before the run.
- **Runtime estimate:** 100+ searches ≈ a few minutes of CPU. Judge fill depends on how
  many new pairs appear (estimated after a pilot on 5 resumes).

### 7.4 Runtime for the full eval (estimates; pilots first)

| Run | Time | Machine load |
|---|---|---|
| Rules only, 60+ documents | seconds | — |
| Groq | ≈25–30 min wall time | Limited by 8,000 tokens a minute; little local CPU |
| Ollama 3B, 60+ documents | ≈1–1.5 h of full CPU | Needs the owner's OK |
| Downstream searches | minutes | Plus judge fill as above |

## 8. Failure cases

| Case | Detection | What the user sees |
|---|---|---|
| Scanned or image-only PDF | Fewer than 200 extractable characters, or most pages with no text layer | "This PDF looks like a scan, so we can't read its text. Upload a PDF exported from your editor, or a Word file. You can also fill in your profile by hand." **No OCR in 5c** (owner decision; in the backlog). |
| Multi-column layout | Column grouping (§1.2); a check for interleaved lines | Measured in §7. The review screen's snippets make wrong reading order visible, and nothing is saved unconfirmed. |
| Non-English resume | Share of English stopwords below a threshold | "Only English resumes can be read for now." Nothing goes to the LLM. |
| Password-protected PDF | pdfminer's encryption flag | "This PDF is password-protected. Remove the password and upload it again." |
| Too big or too long | 5 MB; more than 10 pages; 60k characters; DOCX zip limits | The limit that was hit, in words, for example "This resume has 14 pages; we read up to 10." |
| Wrong type, corrupt, macros | Magic bytes, ZIP checks, parser exception | "We couldn't open this file. Export it again as PDF or Word (.docx)." |
| Hidden text | §2.2 | The parse continues; the review screen shows what was ignored. |
| Name not found for redaction | §1.4 | Asked before the LLM step: continue, or parse on this server only. |
| No allowed LLM available | `LLMUnavailableError`, or the user chose local and Ollama is off | Rule-based fields for review, plus: "Some fields need filling in by hand today." |
| Worker restart or timeout | Stale `extracting`; job timeout | `failed`, with "Something interrupted the parse. Try again." |

Each row has a synthetic test document and a test.

## 9. Backend changes queued from 5a, and order of work

| Change | Detail |
|---|---|
| Real `field` on the profile | `SearchProfile.field`: one of the five fields or "other" plus text. Search uses it as today's `query` does. The 5a browser shape migrates `query` into `field`. |
| Native salary currency | A `min_salary` rule with `{amount, currency, interval}`. The backend converts with `fx_rates.yaml`, the single source for rates, exposed at `GET /api/v1/fx`; the frontend drops `src/lib/fx.ts`. `min_salary_usd` stays accepted for the eval harness. |
| Friendly rule text | `describe()` uses country names and words, not enum values. The frontend's `breachText` workaround is removed. |
| Card fields the API lacks | The `JobExtras` list in [phase-5.md](phase-5.md), added to `JobSummary` as an additive change. |

These are additive. The Phase 4 harness runs before and after, and the NDCG@10 gate must
not move.

**Order of work:**
1. Queued backend changes.
2. Storage, encryption, deletion (deletion test first) and the inactivity cleanup.
3. Profile, dealbreaker, feedback and settings endpoints, plus browser migration.
4. Synthetic, attack and failure documents with the CI guard.
5. File security and the parsing job with its states.
6. Rules extraction and redaction, measured on their own.
7. The model pilot (after the owner's OK), then LLM extraction and consent.
8. Review screen.
9. Extraction eval and downstream eval.
10. Report and PR.

Runtime estimates come before any step over 5 minutes of full CPU.

**Backlog (not 5c):**
- OCR for scanned PDFs (Tesseract).
- Non-English resumes.
- Email verification and password reset.
- Warning email before inactivity deletion (needs email sending).

## 10. Decisions (owner, 2026-11-28)

1. **Original file:** kept, encrypted, latest only, deletable any time. Users can opt in
   to "Delete the original after parsing". Phase 6 tailoring edits the user's own
   resume.
2. **Field:** a fixed list from the existing taxonomy (`ml_ai`, `data`, `backend`,
   `full_stack`, `product_analyst`) plus "Other (free text)".
3. **OCR:** not in 5c. Scanned and image-only PDFs are detected and get a plain message.
   OCR goes to the backlog.
4. **Local model:** 3B only. The pilot compares `llama3.2:3b` and `qwen2.5:3b` on
   accuracy and JSON validity, and the choice is made on measured results.
5. **"Confirm all":** for high-confidence fields only. Low-confidence fields are
   confirmed one by one.
6. **Inactive accounts:** deleted after 12 months by a tested cleanup job, and
   documented.
7. **Eval goals:** as in §7.2, reported against what was measured, with Groq and Ollama
   reported separately.
8. **Upload limits:** 5 MB and at most 10 pages.

**Still proposed (confirm or change):**
- Upload rate limit of 3 a minute and 10 a day per user.
- The 7-day expiry for unconfirmed parses.
- The 120-second job timeout.
