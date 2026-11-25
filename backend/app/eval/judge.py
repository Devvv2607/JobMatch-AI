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

import json
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.llm.client import LLMClient
from app.core.llm.prompts import Prompt, load_prompt
from app.core.llm.types import LLMSchemaError, LLMUnavailableError
from app.eval.pairs import EvalPair, JudgeRecord, append_jsonl, load_judge
from app.eval.profiles import EvalProfile

PROMPT_NAME = "eval_judge"
PROMPT_VERSION = 1
DESCRIPTION_CHARS = 3500


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


def pair_input(profile: EvalProfile, pair: EvalPair) -> str:
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
        "description": job.description[:DESCRIPTION_CHARS],
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


async def judge_pairs(
    pairs: Sequence[EvalPair],
    profiles: dict[str, EvalProfile],
    llm: LLMClient,
    out: Path,
    *,
    tokens_per_minute: int = 6000,
    max_requests: int = 800,
    sleep: Callable[[float], Awaitable[None]],
    clock: Callable[[], float] = time.monotonic,
    prompt_version: int = PROMPT_VERSION,
) -> JudgeRun:
    """Judges every pair not yet in `out`, appending one JudgeRecord per pair."""
    prompt = judge_prompt(prompt_version)
    done = load_judge(out)
    run = JudgeRun(skipped_existing=sum(p.pair_id in done for p in pairs))
    requests = 0
    for pair in pairs:
        if pair.pair_id in done:
            continue
        if requests >= max_requests:
            run.stopped_at_cap = True
            break
        started = clock()
        try:
            verdict, result = await llm.complete_structured(
                prompt,
                pair_input(profiles[pair.profile_id], pair),
                JudgeVerdict,
                data_class="public",
                max_tokens=400,
            )
        except (LLMUnavailableError, LLMSchemaError):
            run.failed += 1  # not written, so the next run retries it
            continue
        append_jsonl(
            out,
            JudgeRecord(
                pair_id=pair.pair_id,
                label=verdict.label,
                reason=verdict.reason,
                confidence=verdict.confidence,
                provider=result.provider,
                model=result.model,
                prompt=f"{PROMPT_NAME}/v{prompt.version}",
                cached=result.cached,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            ),
        )
        if result.cached:
            run.from_cache += 1
            continue
        requests += 1
        run.judged += 1
        # Spend at most `tokens_per_minute`: a call of T tokens occupies T/TPM minutes.
        budget = (result.prompt_tokens + result.completion_tokens) / tokens_per_minute * 60
        if (wait := budget - (clock() - started)) > 0:
            await sleep(wait)
    return run
