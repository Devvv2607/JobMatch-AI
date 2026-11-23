"""The optional LLM sentence for one match, fetched lazily (PLAN.md §2.1).

The model receives the computed explanation object and nothing else: no description
text, no resume text. Its output is checked against that object: if the sentence names a
taxonomy skill that is not in the object's matched or missing lists, it is dropped and
the client shows the computed explanation alone.

The object holds the candidate's skills and experience, so the call is data class
"personal" (never routed to a provider that may train on inputs).

Quota: LLM_DAILY_QUOTA_PER_USER sentences per user per UTC day, counted in Redis when a
request reaches the LLM step (cache hits included, so the count is predictable).
"""

import logging
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.errors import RateLimitedError
from app.core.llm.client import LLMClient
from app.core.llm.prompts import load_prompt
from app.core.llm.types import LLMSchemaError, LLMUnavailableError
from app.core.metrics import EXPLANATION_SENTENCES
from app.ingest.skills import extract_skills
from app.retrieval.scoring import Explanation

logger = logging.getLogger(__name__)

PROMPT_NAME = "match_explanation"
PROMPT_VERSION = 1
_QUOTA_PREFIX = "quota:llm:"


class _Sentence(BaseModel):
    sentence: str = Field(min_length=1, max_length=400)


class QuotaExceededError(RateLimitedError):
    code = "quota_exceeded"


async def take_quota(redis: Redis, user_id: uuid.UUID, limit: int) -> int:
    """Counts one use for today and returns how many remain. Raises 429 past the limit.
    Fails open if Redis is down, like the rate limiter."""
    now = datetime.now(UTC)
    key = f"{_QUOTA_PREFIX}{user_id}:{now:%Y%m%d}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, 2 * 86400)
            used, _ = await pipe.execute()
    except RedisError:
        logger.error("llm quota unavailable, failing open")
        return limit
    if used > limit:
        seconds_left = 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        raise QuotaExceededError(
            "Daily limit for AI explanations reached. The computed explanation is still shown.",
            headers={"Retry-After": str(seconds_left)},
        )
    return int(limit - used)


def unsupported_skills(sentence: str, explanation: Explanation) -> list[str]:
    """Taxonomy skills the sentence names that the explanation does not contain."""
    known = {s.lower() for s in explanation.skills.matched + explanation.skills.missing}
    return [s for s in extract_skills(sentence) if s.lower() not in known]


async def write_sentence(
    llm: LLMClient, explanation: Explanation
) -> tuple[str | None, str, str | None]:
    """(sentence or None, status, detail)."""
    prompt = load_prompt(PROMPT_NAME, PROMPT_VERSION)
    payload = f"<match>\n{explanation.model_dump_json()}\n</match>"
    try:
        # Reasoning models (gpt-oss on Groq) count their reasoning against max_tokens:
        # at 200 the JSON was cut off (Groq: json_validate_failed; 333 tokens were used).
        # The sentence itself is capped by the schema.
        parsed, _ = await llm.complete_structured(
            prompt, payload, _Sentence, data_class="personal", max_tokens=1024
        )
    except (LLMUnavailableError, LLMSchemaError) as exc:
        EXPLANATION_SENTENCES.labels("unavailable").inc()
        logger.warning("match sentence unavailable", extra={"error": type(exc).__name__})
        return None, "unavailable", "No AI provider could write the sentence"
    sentence = " ".join(parsed.sentence.split())
    if extra := unsupported_skills(sentence, explanation):
        EXPLANATION_SENTENCES.labels("dropped").inc()
        logger.info("match sentence dropped", extra={"unsupported_skills": extra})
        return None, "dropped", f"The sentence named skills not in the match: {', '.join(extra)}"
    EXPLANATION_SENTENCES.labels("ok").inc()
    return sentence, "ok", None
