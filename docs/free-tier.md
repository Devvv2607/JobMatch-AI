# Free-tier limits

Everything in JobMatch must run at zero cost. This file records the limits of each hosted
service we depend on, **as published on the date checked**. Providers change these often:
re-check before relying on a number, and update the date when you do.

## Groq (default LLM provider)

Checked **2026-11-24** against <https://console.groq.com/docs/models>,
<https://console.groq.com/docs/rate-limits> and <https://console.groq.com/docs/deprecations>,
and against this project's Groq account (`GET /models` and response headers).

- **Models we use:** `openai/gpt-oss-120b` (`GROQ_MODEL`, production) and
  `qwen/qwen3.8-27b` with `reasoning_effort: none` (`GROQ_FAST_MODEL`, the match
  sentence). Qwen is a **Preview** model ("intended for evaluation purposes only ... may
  be discontinued at short notice"); if it disappears, the startup check disables it and
  the documented fallback is `GROQ_FAST_MODEL=openai/gpt-oss-20b` with
  `GROQ_FAST_REASONING_EFFORT=low` (production; 15/15 valid sentences at 200 tokens,
  p50 477 ms, on 2026-11-23).
- **Shut down:** `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`, on 2026-08-16
  (deprecations page; replacements named there: gpt-oss-120b and gpt-oss-20b). The
  models page still lists both as production, but neither is in this account's
  `/models` and calls return 404. The repo default was llama-3.3-70b-versatile until
  this date.
- **Limits measured on this account** (`x-ratelimit-limit-*` response headers,
  2026-11-24): both models **1,000 requests/day, 8,000 tokens/minute**. Requests are per
  day and tokens per minute (the docs: x-ratelimit-limit-requests "Always refers to
  Requests Per Day", -tokens "Tokens Per Minute"). The public table shows the same row
  for both models, 30 RPM / 1K RPD / 8K TPM / 200K TPD, but describes itself as "the base
  limits for the Developer plan", and the models page shows 1K RPM / 250K TPM for the
  same models; the account headers are the numbers to trust. Exact limits for an
  organisation: `console.groq.com/settings/limits`. Limits apply per organisation.
- With the match sentence's 50-per-user daily quota, 1,000 requests/day covers about 20
  active users a day.
- Structured output: JSON object mode on every model we use; the client validates every
  response against a Pydantic schema regardless.
- **Startup check:** the API asks each enabled provider's `/models` at startup; a
  configured model that is not listed is logged as an error, shown as
  `llm_model_available 0` in `/metrics`, and routed around (no calls are sent to it).
- Retry: `retry-after` (seconds) is set on 429; the client honours it, capped at 8 s.

## Google Gemini (first fallback)

Checked **2026-11-17** against <https://aistudio.google.com/docs/rate-limits>,
<https://aistudio.google.com/docs/pricing>, <https://aistudio.google.com/docs/models> and
<https://aistudio.google.com/docs/openai>.

- Free tier exists for our default `gemini-3.5-flash-lite`, and also for
  `gemini-3.1-flash-lite`, `gemini-3.6-flash`, `gemini-3.8-flash` and `gemini-4-hydrogen`
  (pricing page: input and output "Free of charge", standard tier only).
- **Per-model free-tier rate limits are not published on the docs page**; it says they
  "can be viewed in Google AI Studio". Read them there for your key.
- **Privacy:** for every free-tier model above, the pricing page says free-tier data is
  "used to improve our products". Gemini therefore never receives personal data; see
  "Data routing" below.
- OpenAI-compatible endpoint:
  `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`, bearer auth.
  The page does not say whether `response_format: {"type": "json_object"}` is accepted.
  **Unverified until Phase 4**, when a key is available; if it is rejected, the provider
  adapter will drop the flag for Gemini and rely on schema validation and repair.

## Ollama (last fallback)

Local, no limits, no data leaves the machine. Off by default (`OLLAMA_ENABLED=false`);
needs Ollama running on the host.

## Job sources (Phase 2)

Checked **2026-11-17**. All are public, unauthenticated GET endpoints.

| Source | Endpoint | Published limits and terms |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | No auth for GET. No rate limit published. |
| Lever | `api.lever.co/v0/postings/{site}?mode=json` (`skip`/`limit` paging) | No limit published for reads (only application POSTs: 2/s). Only published postings are exposed. |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true` | No limit or terms published in the docs. |
| Remotive | `remotive.com/api/remote-jobs` | **At most 4 fetches a day; more than 2 a minute are blocked.** Jobs delayed 24 h. Must link to the Remotive job URL **and** name Remotive as the source wherever its jobs are shown. Must not resubmit to third-party job sites (Google Jobs, LinkedIn, Jooble, Neuvoo) or use the jobs to collect signups. The free feed returned **17 jobs** on 2026-11-17. |

How we stay within them: boards are fetched at most 4 at a time with a 30 s timeout;
`check-boards` waits 0.25 s between boards; Remotive is fetched at most once per 6 hours.
The scheduled ingest is off by default; when on, it runs twice a day. Every request sends
a `jobmatch-ingest/0.1` User-Agent.

## Embedding model

`BAAI/bge-small-en-v1.5` (MIT licence), downloaded from Hugging Face once at image build
time and baked into the image. No hosted inference, no cost.

## Not yet checked

Vapi (Phase 8) and deploy hosts (Phase 10) are checked in the phase that first uses them.

## Data routing (decided 2026-11-17)

Every LLM call declares `data_class`. Personal data (resume text, profile, tailoring,
verifier, interview answers, agent turns with user context, anything from `eval/private/`)
goes only to **Groq, then Ollama, never Gemini**. Public data (job descriptions, fictional
eval profiles, the labelling judge on fictional profiles) may use Groq, then Gemini, then
Ollama. The client enforces this in code and raises an error rather than send personal
data to a disallowed provider.

The owner turns on **Zero Data Retention** in Groq's Data Controls for the project's
organisation. That is an account setting the code cannot verify.

Full reasoning and the tests that prove it:
[decisions/0001-llm-data-routing.md](decisions/0001-llm-data-routing.md).
