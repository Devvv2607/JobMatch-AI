# Free-tier limits

Everything in JobMatch must run at zero cost. This file records the limits of each hosted
service we depend on, **as published on the date checked**. Providers change these often:
re-check before relying on a number, and update the date when you do.

## Groq (default LLM provider)

Checked **2026-11-17** against <https://console.groq.com/docs/rate-limits> and
<https://console.groq.com/docs/models>.

- The public rate-limit table says it shows "the base limits for the Developer plan". The
  page has a "Free Plan Limits" tab label but does not publish free-plan numbers in the
  fetched content. **The authoritative numbers for your account are at
  `console.groq.com/settings/limits`.** Limits apply per organisation, not per user.
- Rows in the public table relevant to us (Developer-plan base limits, not verified as
  free-plan limits):

  | Model | RPM | RPD | TPM | TPD |
  |---|---|---|---|---|
  | `openai/gpt-oss-120b` | 30 | 1K | 8K | 200K |
  | `openai/gpt-oss-20b` | 30 | 1K | 8K | 200K |
  | `qwen/qwen3.8-27b` | 30 | 1K | 8K | 200K |

- Our default model, `llama-3.3-70b-versatile`, is listed as a production model
  (131,072-token context) but **is not in the public rate-limit table**. Check its limits
  in the console.
- Structured output: strict `json_schema` is supported only on `openai/gpt-oss-20b`,
  `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` and `meta-models/muse-spark-open`. Every model,
  including our default, supports `json_object` mode, which is what the client uses; the
  client validates every response against a Pydantic schema regardless.
- Rate-limit headers: `x-ratelimit-*-requests` refer to requests per **day**,
  `x-ratelimit-*-tokens` to tokens per **minute**; `retry-after` (seconds) is set on 429.
  The client honours `retry-after`, capped at 8 s.

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
  "used to improve our products". Resume text is personal data. See the open question at
  the end of this file.
- OpenAI-compatible endpoint:
  `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`, bearer auth.
  The page does not say whether `response_format: {"type": "json_object"}` is accepted.
  **Unverified until Phase 4**, when a key is available; if it is rejected, the provider
  adapter will drop the flag for Gemini and rely on schema validation and repair.

## Ollama (last fallback)

Local, no limits, no data leaves the machine. Off by default (`OLLAMA_ENABLED=false`);
needs Ollama running on the host.

## Not yet checked

Vapi (Phase 8), the remote-jobs API and ATS endpoints (Phase 2), and deploy hosts
(Phase 10) are checked in the phase that first uses them.

## Open question for the owner

Both free LLM tiers may use submitted content. Gemini's pricing page says free-tier data
is used to improve products; Groq's data-use terms were not checked yet. Resume parsing
and tailoring send resume text to the LLM. Options: (a) accept it and say so plainly in
the UI and README, (b) send resume text only to Ollama (local) and use hosted providers
for job-only prompts, (c) decide per provider after reading Groq's terms. This needs an
answer before Phase 5 (resume parsing).
