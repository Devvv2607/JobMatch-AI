# ADR 0001: Route LLM calls by data class

- Status: accepted
- Date: 2026-11-17
- Decided by: project owner

## Context

JobMatch sends text to hosted LLMs on free tiers. Some of that text is personal data:
resume text, the parsed profile, tailored bullets, verifier inputs, interview answers,
and agent turns that carry user context. The rest is public or fictional: job postings,
fictional eval profiles, and the labelling judge run over those fictional profiles.

Gemini's pricing page (checked 2026-11-17) says free-tier data is "used to improve our
products". Groq offers Zero Data Retention under Data Controls, which the owner turns on
for the project's Groq organisation. Ollama runs locally, so nothing leaves the machine.

## Decision

Every LLM call declares `data_class`, either `"personal"` or `"public"`. The argument is
required, with no default, so a caller cannot forget it.

| data_class | Providers, in fallback order |
|---|---|
| `personal` | Groq → Ollama. **Never Gemini.** |
| `public` | Groq → Gemini → Ollama |

- The policy is the `ALLOWED_PROVIDERS` constant in `app/core/llm/types.py`. It lives in
  code, not configuration, so changing an environment variable cannot weaken it.
  `LLM_PROVIDER_ORDER` only orders and enables providers inside what the policy allows.
- Per call, the client keeps only the allowed providers, in order. If none is configured,
  it raises `LLMUnavailableError` and the feature uses its degraded mode.
- As a second check, the one method that sends a request refuses a provider not allowed
  for the call's class. It raises `DataRoutingError`, which is deliberately not a
  `ProviderError`, so the fallback loop cannot swallow it and move on.
- Cache lookups for a personal call only consider entries written by allowed providers.
- A provider name not in the policy (for example, a new one added later) receives no data
  of either class until the policy is changed in code and reviewed.
- Files under `eval/private/` (the owner's real resume) are personal. Any eval that reads
  them must call with `data_class="personal"`.

## Consequences

- Personal features depend on Groq, or on Ollama running locally. When Groq is
  rate-limited and Ollama is off, resume parsing, tailoring, verification, interview
  scoring and the agent fall back to their degraded modes instead of using Gemini.
- Each call site has to state its class. Reviews should check that anything touching a
  resume, profile or user turn says `personal`.
- Tests in `backend/tests/test_llm_client.py` prove that: personal data never reaches
  Gemini even when Groq fails; public data may; a personal call fails rather than use a
  disallowed provider; schema repair stays on the same allowed provider; the send path
  itself blocks a disallowed provider; unknown providers receive nothing; and a personal
  call does not read a Gemini-written cache entry.
- Groq Zero Data Retention is an account setting outside this repo. The code cannot
  check it.
