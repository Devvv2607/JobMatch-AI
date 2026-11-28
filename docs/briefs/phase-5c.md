# Phase 5c: Resume parsing and stored profiles

Draft 2026-11-28, for the owner's review before any code. Branch `phase-5c-profile`,
started from main once Phase 4 has merged and Docker is free.

5c turns the 5a profile, which lives in the browser, into an account profile stored on
the server. That profile can come from a parsed resume, and every parsed fact links back
to the place in the resume it came from. It also ships the backend changes queued in 5a.

Sources: [PLAN.md](../../PLAN.md) §2.2 (resume engine), §3 (schema);
[ADR 0001](../decisions/0001-llm-data-routing.md) (LLM routing by data class);
[phase-5.md](phase-5.md) (5a decisions and the API gaps list); the 25 fictional eval
profiles (`eval/profiles/p01–p25.yaml`, on `phase-4-eval` until Phase 4 merges).

**Ground rules for the whole phase**

- **No human labelling.** Extraction quality is measured on synthetic resumes whose
  ground truth is known because we generate them (see Evaluation).
- **No real resume in git:** not in commits, fixtures, test data or screenshots. Synthetic
  resumes only. The owner's real resume stays in `eval/private/`, which is gitignored and
  read only by evals that run with `data_class="personal"`.
- **Personal data never goes to Gemini** (ADR 0001). Resume text, parsed fields and
  anything derived from them are `personal`: Groq first, then Ollama on this machine.
- **Free tools only.** Every library below is free and open source. No paid OCR or
  parsing APIs.
- **Nothing is auto-trusted.** Parsed fields are suggestions until the user confirms or
  edits each one.

---

## 1. Parsing pipeline

```
upload (API) → checks → store encrypted temporary file → enqueue parse_resume (arq worker)
worker: text extraction with character offsets → layout normalisation → deterministic
        extractors → contact redaction → LLM extraction (personal: Groq → Ollama)
        → span validation → ParseResult (status: needs_review) → user review screen
        → user confirms → candidate_profiles + resume_spans
```

### 1.1 Upload checks (API, before anything is stored)

- File size is 5 MB or less; the 5a browser check stays, and the server checks again.
- The file type comes from the file's content, never its name or `Content-Type`:
  - PDF: starts with `%PDF-`.
  - DOCX: a ZIP archive that contains `word/document.xml` and no `vbaProject.bin`.
    Macro-enabled `.docm` files are rejected.
- DOCX archive limits: at most 50 MB unzipped and at most 2,000 entries (guards against
  zip bombs).
- Per-user rate limit (a Redis counter like the existing ones): for example, 10 uploads
  a day.

### 1.2 Text extraction (worker, local, free)

| Format | Library (licence) | What we keep |
|---|---|---|
| PDF | `pdfplumber` on `pdfminer.six` (MIT) | Characters with positions, grouped into words and lines. The output is one plain-text string plus a map from each character in it back to its page and bounding box. |
| DOCX | `python-docx` (MIT), with XML parsed through `defusedxml` | Paragraphs and table cells in document order, as one plain-text string. Offsets point into that string. |

- **Not PyMuPDF.** It's faster, but its AGPL licence is a poor fit for this repo.
  `pdfplumber` is fast enough for single resumes: a 2-page CV should take well under
  1 second. To be measured.
- **Columns:** words are grouped into columns by gaps in their x-positions, then each
  column is read top to bottom. A two-column resume must not interleave its lines. The
  synthetic set includes two-column layouts so this is measured, not assumed (see §6).
- **One canonical text string per resume.** All spans are offsets into it, so it must
  never change after the parse (see §2).
- **Limits:** at most 10 pages and 60,000 characters of text, and the worker job times
  out after 60 seconds. Anything over a limit becomes a clear error message (see §7).

### 1.3 Deterministic extraction first

Rules handle everything they can, and each rule records the span it matched:

| Field | Rule |
|---|---|
| Email, phone, URLs (LinkedIn, GitHub, portfolio) | Regex. Used **only for redaction** (§1.4); not stored in the profile. |
| Section boundaries | Headings matched against a list ("Experience", "Work history", "Education", "Skills", "Projects"…), using case and line position. |
| Date ranges | Regex for "Jan 2022 – Present", "2019–2021", "03/2020 - 08/2023" and similar. "Present" or "Current" means the upload date. |
| Years of experience | Merge the date ranges in the Experience section, counting overlapping periods once, and sum them. Internships are counted separately, so the user can choose whether to include them (5a's wording already says "internships included"). |
| Skills | The existing taxonomy matcher (`app/ingest/skills.py`), run on the text. It already returns regex matches, so each skill comes with its span. |
| Degree | Patterns such as B.Tech, B.E., BSc, MSc, M.Tech, MBA, PhD, "Bachelor of…", plus a graduation year. |
| Level (suggested) | The existing title-to-seniority rules (`app/ingest/seniority.py`) applied to the most recent job title, then checked against the years of experience using the same bands as `EXPECTED_YEARS`. |

### 1.4 LLM extraction, only for what rules can't do

- **What the LLM handles:**
  - Job titles and employers (prose varies too much for rules).
  - Skills that aren't in the taxonomy.
  - The education institution.
  - **Field**, chosen from a fixed list. The list starts from the eval profiles' `field`
    values and adds "other: free text". It is proposed as an owner decision.
  - A level, when the rules disagree with each other or find nothing.
- **Data class `personal`.** Groq (Zero Data Retention on) first, then Ollama. Never
  Gemini. When neither is available, the parse finishes with the rule-based fields only
  and the review screen says the rest needs filling in by hand.
- **Redaction before sending:** email addresses, phone numbers and URLs are replaced with
  placeholders of the **same length**, so offsets in the LLM's answer still point at the
  right place in the stored text. The candidate's name is not redacted, because no
  reliable rule exists; Groq ZDR covers it.
- **Prompt rules follow PLAN.md:**
  - The resume goes in a delimited block in the user turn, never in the system prompt.
  - The output must be JSON matching a Pydantic `ParsedResume` schema, with the existing
    bounded repair step.
- **Every item must quote its source:** the LLM returns each item as
  `{value, quote, start, end}`, and the span checks in §2 decide whether it can be used.
- **No LLM cache for personal calls.** `llm_cache` is keyed by a hash of the input, so a
  cached row would hold personal output. Resume calls bypass the cache.

### 1.5 Local model: runtime and RAM (estimates, to be measured)

Machine: Ryzen 7 7445HS, 12 threads, 15 GB RAM, CPU only.

| Model (Q4 GGUF via Ollama) | Disk | RAM while running | One resume (≈3k tokens in, ≈800 out) |
|---|---|---|---|
| `llama3.2` 3B (current `OLLAMA_MODEL` default) | ≈2.0 GB | ≈3 GB | ≈40–90 s |
| A 7–8B instruct model (e.g. Qwen2.5 7B) | ≈4.7 GB | ≈6 GB | ≈2–4 min |

- These are rough figures for CPU-only Q4 inference, not measurements.
- **Before relying on them:** a 3-resume pilot, timed with peak RAM recorded, and only
  with the owner's OK.
- With Docker and the API running, a 7B model leaves little headroom on 15 GB. The
  proposal is 3B as the Ollama fallback, with the eval reporting its accuracy separately
  so the cost of falling back is visible.
- Groq for comparison: ≈4k tokens per resume against the account's 8,000 tokens a
  minute, so about 2 resumes a minute. Network-bound; it uses no local CPU.

## 2. Provenance and user confirmation

- **Every extracted fact keeps its source span:** each item is `{value, span: {start,
  end}, quote, source: "rule" | "llm" | "user", status}`.
- **Span check, done in code:** `text[start:end] == quote`. If the LLM's offsets are
  wrong but the quote appears exactly once in the text, the span is corrected to that
  place. If the quote appears zero times or more than once, the item is shown as
  "couldn't find this in your resume" and starts unconfirmed.
- **Stored text and spans:**
  - The canonical text is stored once, encrypted (§3).
  - The spans are stored in `resume_spans` (PLAN §3), which Phase 6 needs for the
    experience bank and the verifier.
  - Spans point into an immutable `resume_text_version`. Re-uploading creates a new
    version; it never edits the old one.
- **Review screen (built on the 5a profile sections and shared controls):**
  - Each suggested field shows its value and the highlighted snippet it came from.
  - Each field can be confirmed, edited or removed.
  - "Confirm all" exists but stays disabled until the user has opened every section.
    This is proposed; it's an owner decision.
- **Nothing is saved to `candidate_profiles` until the user confirms.**
  - Until then the parse result is stored as `resume_parses.status = needs_review` and
    expires after 7 days.
  - An edited field keeps its original span (it still came from the resume), and its
    source becomes `user`.
  - A field the user adds by hand has no span.
- **Matching and tailoring use only confirmed facts.** Phase 6 tailoring may cite only
  confirmed spans.

## 3. Storage and privacy

### 3.1 What is stored, and where

| Data | Stored? | Where | Retention |
|---|---|---|---|
| Uploaded file (PDF/DOCX) | Only while it's being parsed | Docker volume outside the web root, encrypted | Deleted as soon as text extraction finishes, successful or not. A file whose job never ran is removed by a cleanup cron after 24 h. |
| Extracted canonical text | Yes (needed for spans) | `resumes.text_encrypted` | Until the user deletes it or replaces the resume |
| Parse result awaiting review | Yes | `resume_parses` (encrypted JSONB) | 7 days, then deleted |
| Confirmed profile | Yes | `candidate_profiles` (encrypted JSONB for the item list; plain columns for the fields search filters on: skills, years, preferences) | Until the user deletes it |
| Dealbreakers, feedback | Yes | `dealbreakers`, `job_feedback` | Until the user deletes them |
| Contact details (email, phone, URLs) | **No** | (redaction only) | Never stored |

Proposed owner decision: **do not keep the original file.** Phase 6 tailoring works from
the text and spans and exports a newly generated document, so the original isn't needed.
Keeping it would add risk for no feature.

### 3.2 Encryption at rest

- **Application-level encryption** with AES-256-GCM, using the `cryptography` package
  (Apache-2.0/BSD).
  - Applies to the resume text, the parse results, the item list (JSONB) and the
    temporary file.
  - The key comes from `PROFILE_ENCRYPTION_KEY` in `.env`. The owner creates it; it is
    never printed or committed.
  - Each ciphertext records which key encrypted it, so keys can be rotated with a
    re-encrypt command.
- **The skills, years and preferences that search filters on stay in plain columns.**
  The search SQL needs them. They are less sensitive than resume text, but they are
  still deleted with everything else.
- **Disk encryption (BitLocker) is the host's job.** The README says so; the code can't
  check it.

### 3.3 Logs and traces

- **Logs:**
  - The structured JSON logger gets a redaction filter for email addresses, phone
    numbers and tokens.
  - Logs never contain resume text, parsed values or LLM prompt and response bodies for
    personal calls. They record only the request id, token counts, latency, provider,
    model and status.
  - A test logs a synthetic resume through the whole pipeline and checks that none of
    its text appears in the captured logs.
- **Langfuse** (behind `--profile tracing`, off by default):
  - For personal calls, the trace's input and output go through Langfuse's masking hook
    and become `[personal: N chars]`. Only metadata is kept.
  - Traces are tagged with a hashed user id, so "delete my data" can find and delete
    them through the Langfuse API.
- **Errors:** exception messages from the parser never include document text. Sentry is
  still Phase 10, and gets the same scrubber when it lands.

### 3.4 "Delete my data"

- **Two separate actions:**
  - `DELETE /api/v1/me/data`: deletes the profile data and keeps the account.
  - Account deletion: deletes everything, account included.
- **What "everything" covers:**
  - `resumes`, `resume_parses`, `resume_spans` (including their Phase 6 embeddings),
    `candidate_profiles`, `dealbreakers`, `job_feedback` and `digests`.
  - Any temporary files on disk.
  - The user's Redis keys: quotas and cached search results keyed by profile.
  - Queued arq jobs for that user, which are cancelled.
  - Langfuse traces, when tracing is on.
  - `background_tasks` result rows.
- **The test proves it, rather than listing tables by hand:**
  - It finds every table with a `user_id` column, creates data in each, deletes, and
    asserts zero rows remain.
  - It also checks the file directory and the user's Redis keys.
  - A new user-owned table added later fails the test until deletion covers it.
- **The frontend's "Clear my data"** (5a) also calls this endpoint when signed in, and
  says which of the two it did.

### 3.5 No real resumes in the repo

- **Synthetic resumes** live in `eval/synthetic_resumes/`. They are generated by a script
  and committed with the script that made them.
- **CI guard, a new step inside the existing backend job** (no new or renamed job): it
  fails if any `.pdf` or `.docx` is committed outside `eval/synthetic_resumes/`, or if a
  file there lacks the generator's marker.
- `eval/private/` stays gitignored, and the guard also fails if anything under it is
  tracked.

## 4. Accounts

- **Reuse the Phase 1 auth unchanged:**
  - Email and password with Argon2.
  - Access token kept in memory.
  - Rotating refresh token in an httpOnly cookie, with reuse detection.
  - The `X-Requested-With` CSRF header.
- **That is the minimum needed:** every new profile endpoint requires a signed-in user,
  and every row is scoped by `user_id`. No email verification or password reset in 5c;
  they are listed for later.
- **Endpoints:**
  - `POST /api/v1/resumes`: upload.
  - `GET /api/v1/resumes/{id}/parse`: poll the parse task through the existing
    `background_tasks` pattern.
  - `POST /api/v1/resumes/{id}/confirm`.
  - `GET` and `PUT /api/v1/profile`, which returns and accepts the 5a `StoredProfile`
    shape.
  - `GET` and `PUT /api/v1/dealbreakers`.
  - `POST` and `DELETE /api/v1/feedback`.
  - `DELETE /api/v1/me/data`.
- **Search reads the stored profile:** `POST /search` without a `profile` uses the
  signed-in user's stored profile and dealbreakers, as PLAN.md planned. Sending one in
  the request still works, for the eval harness.
- **Migrating the browser profile into an account (one-off, on sign-in):**
  - Browser profile present, account has none: offer "Save the profile from this browser
    to your account". It uploads, and the browser copy is removed after the server
    confirms.
  - Both present and different: show both summaries and let the user choose which to
    keep. Never merge silently.
  - Saved and hidden jobs (`jobmatch.feedback.v1`) are uploaded the same way. Duplicates
    are resolved by `job_id`, keeping the newest.
  - The browser data is versioned (`version: 1`), so the upload validates it with the
    same schema as the API.
  - If the upload fails, the browser copy is kept.

## 5. Backend changes queued from 5a

| Change | Detail |
|---|---|
| Real `field` on the profile | `SearchProfile.field` (from the fixed list in §1.4, or "other: text"). Search uses it like today's `query`. The 5a browser shape migrates `query` into `field`. |
| Native salary currency | A `min_salary` rule with `{amount, currency, interval}` (INR LPA or USD, per year). The backend converts with `fx_rates.yaml`, which becomes the single source of truth for the rate. `GET /api/v1/fx` exposes it so the frontend stops carrying its own constant (`src/lib/fx.ts`). `min_salary_usd` is still accepted, so the eval harness keeps working. |
| Friendly rule text | `describe()` uses country names ("Open to candidates in India") and words instead of enum values ("Employment: full-time, contract"). The frontend's underscore-replacing workaround in `breachText` is then removed. |
| Card fields the API lacks | The `JobExtras` list in [phase-5.md](phase-5.md) (description, snippet flag, eligibility scope, poster type, repost and source counts…), added to `JobSummary` as an additive change. |

These are additive or backward-compatible. The Phase 4 harness runs before and after,
and the NDCG@10 gate must not move, because ranking is not supposed to change.

## 6. Evaluation without human labels

- **Synthetic resumes, with ground truth by construction:**
  - A generator turns each of the 25 eval profiles into resumes. Each persona, field,
    experience band and skill list becomes made-up employers, titles, date ranges,
    education and bullets.
  - It uses fixed templates and seeded random choices, and **no LLM for the facts**. An
    LLM may optionally paraphrase bullet prose (public class, since the content is
    fictional), but the generator re-checks that every fact still appears verbatim.
  - Because the generator places every fact, it knows each fact's exact character span.
- **Layouts:** each profile is rendered in at least 2 of the following, giving 50+
  documents:
  - single-column PDF
  - two-column PDF
  - DOCX with tables
  - "dense" PDF with small type and no headings
  - Rendering uses `reportlab` (BSD) and `python-docx` (MIT).
- **Failure-case documents** (§7) are generated the same way, so every failure path has
  a test.
- **What is reported, per field, overall and split by layout and by provider (Groq vs
  Ollama vs rules only):**

  | Field | Metric | Proposed bar |
  |---|---|---|
  | Skills | precision, recall, F1 vs the profile's skill set (canonical names) | F1 ≥ 0.90 |
  | Years of experience | share within ±0.5 years | ≥ 90% |
  | Level | exact match with the profile's seniority list | ≥ 85% |
  | Field | exact match | ≥ 85% |
  | Education (degree level, institution, year) | exact match per part | ≥ 90% |
  | Span validity | share of extracted items whose quote is at their span | 100% of items saved as confirmed-eligible; the rest are flagged, never silently kept |
  | Contact redaction | share of planted emails, phones and URLs that reach the LLM unredacted | 0 |

- **Wording in the report:** "agreement with constructed ground truth on synthetic
  resumes", never "validated". Synthetic layouts are cleaner than real ones; the report
  says so. The owner's real resume can be run locally as a personal smoke test, with
  results kept out of git.
- **Runtime estimate (to confirm with a pilot first):**
  - Rules only: seconds for all 50+ documents.
  - Groq: about 25–30 min wall time, limited by the 8,000 tokens a minute, with almost no
    local CPU.
  - Ollama 3B: about 50 × 1 min ≈ 1 h of full CPU. This needs the owner's OK under the
    >5-minute rule.
  - Ollama 7B: 2–3 h, so it isn't proposed.

## 7. Failure cases

| Case | Detection | What the user sees |
|---|---|---|
| Scanned or image-only PDF | Fewer than 200 extractable characters, or most pages have no text layer | "This PDF looks like a scan, so we can't read its text. Upload a PDF exported from your editor, or fill in your profile by hand." No OCR in 5c (proposed). Tesseract is free, but slow and error-prone on CVs; it could be added later. |
| Multi-column layout | Column grouping (§1.2); a check for lines that interleave across columns | Measured in §6. If the order is still wrong, the review screen's snippets make it visible, and nothing is saved unconfirmed. |
| Non-English resume | Share of English stopwords in the text, below a threshold | "Only English resumes can be read for now." The user fills the profile by hand. Nothing goes to the LLM. |
| Password-protected PDF | pdfminer's encryption flag | "This PDF is password-protected. Remove the password and upload it again." |
| Huge file, too many pages, too much text | 5 MB, 10 pages, 60k characters, 50 MB unzipped DOCX, 60 s timeout | The limit that was hit, in words, for example "This resume has 14 pages; we read up to 10." |
| Corrupt file or wrong type | Magic bytes; parser exception | "We couldn't open this file. Try exporting it again as PDF or Word." |
| LLM unavailable (Groq limited, Ollama off) | `LLMUnavailableError` | Rule-based fields are shown for review, plus: "Some fields need filling in by hand today." |

Each row has a synthetic test document and a test.

## 8. Order of work

1. Backend queued changes (§5), each with the Phase 4 harness run before and after.
2. Storage, encryption and "delete my data" (§3), with the all-tables deletion test
   written first.
3. Profile, dealbreaker and feedback endpoints, plus migration from the browser (§4).
   The frontend switches from browser storage to the API when signed in.
4. Synthetic resume generator and failure documents (§6, §7), with the CI guard (§3.5).
5. Parsing pipeline: rules first, measured on its own; then the LLM step, measured
   again.
6. Review screen with spans (§2).
7. Eval report and PR.

Runtime estimates are given before any step over 5 minutes of full CPU. Docker is used
only after the owner says Phase 4's judging is done.

## 9. Owner decisions needed

1. **Original file:** delete it right after text extraction (proposed), or keep it,
   encrypted?
2. **Field list:** a fixed list taken from the eval profiles' `field` values plus "other:
   text" (proposed), or free text only?
3. **OCR for scanned PDFs:** not in 5c (proposed), or add Tesseract now?
4. **Ollama fallback model:** `llama3.2` 3B (proposed, about 3 GB RAM), or a 7B model
   (about 6 GB, slower)?
5. **"Confirm all"** on the review screen: allowed only after every section has been
   opened (proposed), or never (one field at a time)?
6. **Retention for confirmed profiles of inactive accounts:** kept until deleted
   (proposed for now), or deleted automatically after a set period?
7. **Eval bars:** the proposed targets in §6.
8. **Upload limit:** 10 a day per user (proposed).
