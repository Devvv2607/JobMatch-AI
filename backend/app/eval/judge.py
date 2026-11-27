"""LLM judge for (profile, job) pairs. Prompt: app/prompts/eval_judge/v<N>.md (the rubric).

- data_class="public": fictional profiles and public postings, so Groq, then Gemini.
- Structured output (JudgeVerdict), validated by the LLM client.
- Cached per pair twice over: the LLM client's prompt cache (same prompt, model and
  input), and judge.jsonl, where every judged pair is appended and fsynced; a restarted
  run skips the pairs already there.
- Paced to stay under a tokens-per-minute budget (Groq's account limit is 8,000 TPM and
  1,000 requests a day, docs/free-tier.md) and stops after `max_requests` calls; run it
  again the next day to continue.
"""

import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.llm.client import LLMClient
from app.core.llm.prompts import Prompt, load_prompt
from app.core.llm.types import LLMQuotaExhaustedError, LLMSchemaError, LLMUnavailableError
from app.eval.pairs import EvalPair, JudgeRecord, append_jsonl, load_judge
from app.eval.profiles import EvalProfile
from app.eval.quota import DailyBudget

logger = logging.getLogger(__name__)

PROMPT_NAME = "eval_judge"
# Room for gpt-oss reasoning (342 completion tokens on average on Groq, 2026-11-26): at
# 400, a long reasoning ran out and came back empty, failing the pair.
MAX_TOKENS = 1024
PROMPT_VERSION = 1
# Owner decision 2026-11-26: the judge reads the structured fields plus the first ~350
# tokens of the stripped description (~1,400 characters, cut at a word), because the
# full 3,500 characters measured 2,027 tokens a pair on 10 real pairs. INPUT_VERSION is
# recorded with every judgement so labels from the two inputs are never mixed silently.
DESCRIPTION_CHARS = 1400
RECOVER_AFTER = 10  # pairs without a 429 before the pace rises by 1 call a minute
INPUT_VERSION = 2  # the default, used for every label so far
# Owner decision 2026-11-27: input v3 trims by section instead (app/eval/trim.py): the
# requirements and any years-of-experience / seniority statement first, boilerplate
# sections last, within V3_CHARS (Groq tokens per pair +16% on average, +27% at most,
# estimated at 3.55 characters a token). Identical to v2 for descriptions <= 1,400.
V3_CHARS = 3200
INPUT_VERSIONS = (2, 3)


def description_input(text: str, input_version: int = INPUT_VERSION) -> str:
    if input_version == 2:
        return lead(text)
    if input_version == 3:
        from app.eval.trim import trim

        return trim(text, V3_CHARS)
    raise ValueError(f"unknown judge input version {input_version}")


def lead(text: str, limit: int = DESCRIPTION_CHARS) -> str:
    """The first `limit` characters, cut back to the last whole word."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return (cut[: cut.rfind(" ")] if " " in cut else cut).rstrip() + " ..."


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: int = Field(ge=0, le=3)
    reason: str = Field(min_length=5, max_length=600)
    confidence: Literal["low", "medium", "high"]


def judge_prompt(version: int = PROMPT_VERSION) -> Prompt:
    return load_prompt(PROMPT_NAME, version)


def rubric_text(version: int = PROMPT_VERSION) -> str:
    """The rubric section of the prompt, shown to the human labeller as well."""
    system = judge_prompt(version).system
    start = system.index("Rubric")
    end = system.index("How to grade")
    return system[start:end].strip()


def pair_input(profile: EvalProfile, pair: EvalPair, input_version: int = INPUT_VERSION) -> str:
    """The user message: one JSON object between <pair> tags."""
    prefs = profile.profile.preferences
    job = pair.job
    candidate = {
        "persona": profile.persona,
        "lives_in": profile.lives_in,
        "years_experience": profile.profile.years_experience,
        "search": profile.query,
        "skills": profile.profile.skills,
        "preferences": {
            "workplace": prefs.workplace or "any",
            "countries": prefs.countries,
            "seniority": prefs.seniority or "any",
        },
        "dealbreakers": profile.dealbreakers(),
        "a_perfect_match_looks_like": profile.judge_notes.a_3_looks_like,
        "rules_a_job_out": profile.judge_notes.rules_out,
    }
    posting = {
        "title": job.title,
        "company": job.company,
        "locations": job.locations or [job.location],
        "eligibility": job.eligibility,
        "workplace": job.workplace,
        "employment_type": job.employment,
        "posted_by": "staffing agency" if job.poster == "staffing_agency" else "employer",
        "salary": job.salary or "not stated",
        "description": description_input(job.description, input_version),
    }
    body = json.dumps({"candidate": candidate, "job": posting}, ensure_ascii=False, indent=1)
    return f"<pair>\n{body}\n</pair>"


@dataclass
class JudgeRun:
    judged: int = 0
    from_cache: int = 0
    skipped_existing: int = 0
    failed: int = 0
    stopped_at_cap: bool = False
    stopped_at_daily_quota: bool = False  # the provider's per-day quota: resume tomorrow
    stopped_at_daily_budget: bool = False  # our own cap below that quota (app/eval/quota.py)
    requests_today: int | None = None  # the provider's requests this Pacific day, if counted
    stopped_after_failures: bool = False  # `max_consecutive_failures` pairs in a row failed
    failures: dict[str, int] = field(default_factory=dict)  # error kind -> pairs
    slowed_to_rpm: float | None = None  # set when a 429 halved the pace
    recovered_to_rpm: float | None = None  # the pace after the latest recovery step


async def judge_pairs(
    pairs: Sequence[EvalPair],
    profiles: dict[str, EvalProfile],
    llm: LLMClient,
    out: Path,
    *,
    tokens_per_minute: int = 6000,
    requests_per_minute: float = 0,
    max_requests: int = 800,
    max_consecutive_failures: int = 5,
    max_tokens: int = MAX_TOKENS,
    failures_out: Path | None = None,
    use_cache: bool = True,
    budget: DailyBudget | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]],
    clock: Callable[[], float] = time.monotonic,
    prompt_version: int = PROMPT_VERSION,
    input_version: int = INPUT_VERSION,
) -> JudgeRun:
    """Judges every pair not yet in `out`, appending one JudgeRecord per pair."""
    prompt = judge_prompt(prompt_version)
    loaded = load_judge(out)

    def judged_on_this_input(pair: EvalPair) -> bool:
        # Done only if judged from the same input (owner 2026-11-27): a record whose
        # input_sha256 differs from this run's input is judged again (the later line
        # wins in load_judge). Records from before hashes existed count as done.
        record = loaded.get(pair.pair_id)
        if record is None:
            return False
        if record.input_sha256 is None:
            return True
        text = pair_input(profiles[pair.profile_id], pair, input_version)
        return record.input_sha256 == input_hash(text)

    done = {p.pair_id for p in pairs if judged_on_this_input(p)}
    run = JudgeRun(skipped_existing=len(done))
    requests = 0
    consecutive = 0
    rate_limited = llm.rate_limited
    target_rpm = requests_per_minute
    clean_streak = 0
    for pair in pairs:
        if pair.pair_id in done:
            continue
        if requests >= max_requests:
            run.stopped_at_cap = True
            break
        if budget is not None:
            run.requests_today = await budget.used(now())
            if run.requests_today >= budget.limit:
                run.stopped_at_daily_budget = True
                break
        attempts_before = llm.requests.get(budget.provider, 0) if budget else 0
        calls_before = sum(llm.requests.values())
        started = clock()
        text = pair_input(profiles[pair.profile_id], pair, input_version)
        try:
            try:
                verdict, result = await llm.complete_structured(
                    prompt,
                    text,
                    JudgeVerdict,
                    data_class="public",
                    max_tokens=max_tokens,
                    use_cache=use_cache,
                )
            finally:
                # Every HTTP attempt counts against the provider's day, failed or not.
                if budget is not None:
                    spent = llm.requests.get(budget.provider, 0) - attempts_before
                    run.requests_today = await budget.add(spent, now())
        except LLMQuotaExhaustedError as exc:
            run.stopped_at_daily_quota = True
            logger.warning("judge stopped: daily quota", extra={"error": str(exc)[:300]})
            break
        except (LLMUnavailableError, LLMSchemaError) as exc:
            run.failed += 1  # not written, so the next run retries it
            kind = exc.kind if isinstance(exc, LLMSchemaError) else type(exc).__name__
            if isinstance(exc, LLMSchemaError) and failures_out is not None:
                # The raw output stays local (gitignored), for diagnosis only.
                append_jsonl(
                    failures_out,
                    {
                        "pair_id": pair.pair_id,
                        "kind": exc.kind,
                        "finish_reason": exc.finish_reason,
                        "raw": exc.raw,
                    },
                )
            run.failures[kind] = run.failures.get(kind, 0) + 1
            logger.warning(
                "judge pair failed: %s %s: %s",
                pair.pair_id,
                kind,
                str(exc)[:300],
                extra={"pair_id": pair.pair_id, "error_type": kind},
            )
            consecutive += 1
            if consecutive >= max_consecutive_failures:
                run.stopped_after_failures = True
                break
            # Every HTTP attempt (retries included) counts against the per-minute pace.
            calls = max(1, sum(llm.requests.values()) - calls_before)
            await sleep(calls * _interval(requests_per_minute))
            continue
        consecutive = 0
        if llm.rate_limited > rate_limited:
            # A real 429: halve the pace (never below 2 calls a minute).
            rate_limited = llm.rate_limited
            clean_streak = 0
            if requests_per_minute > 2:
                requests_per_minute = max(2.0, requests_per_minute / 2)
                run.slowed_to_rpm = requests_per_minute
                logger.warning(
                    "judge pace halved after a 429: %.1f calls a minute", requests_per_minute
                )
        elif requests_per_minute < target_rpm:
            # Recover gradually (owner 2026-11-27): +1 call a minute after every
            # RECOVER_AFTER pairs in a row without a 429, up to the configured pace.
            clean_streak += 1
            if clean_streak >= RECOVER_AFTER:
                clean_streak = 0
                requests_per_minute = min(target_rpm, requests_per_minute + 1)
                run.recovered_to_rpm = requests_per_minute
                logger.info("judge pace recovering: %.1f calls a minute", requests_per_minute)
        append_jsonl(
            out,
            JudgeRecord(
                pair_id=pair.pair_id,
                label=verdict.label,
                reason=verdict.reason,
                confidence=verdict.confidence,
                provider=result.provider,
                model=result.model,
                prompt=f"{PROMPT_NAME}/v{prompt.version}+input{input_version}",
                cached=result.cached,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                input_sha256=input_hash(text),
            ),
        )
        if result.cached:
            run.from_cache += 1
            continue
        requests += 1
        run.judged += 1
        # Spend at most `tokens_per_minute` (a call of T tokens occupies T/TPM minutes)
        # and at most `requests_per_minute`.
        pace = (result.prompt_tokens + result.completion_tokens) / tokens_per_minute * 60
        calls = max(1, sum(llm.requests.values()) - calls_before)  # retries count too
        pace = max(pace, calls * _interval(requests_per_minute))
        if (wait := pace - (clock() - started)) > 0:
            await sleep(wait)
    return run


def input_hash(text: str) -> str:
    """sha256 of the exact user message the judge received (the pair JSON in tags)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _interval(requests_per_minute: float) -> float:
    return 60 / requests_per_minute if requests_per_minute > 0 else 0.0
