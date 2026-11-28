"""Daily request budgets for the judge (owner decision 2026-11-26).

Gemini's free tier allows 500 requests a day per project and model
(GenerateRequestsPerDayPerProjectPerModel-FreeTier, seen in its 429 on 2026-11-26); the
count resets at midnight Pacific time, 13:30 IST (12:30 during US daylight time). The
judge stops a little below it (480) rather than failing pair after pair, and says when
to resume. Requests are counted per HTTP attempt (retries included), as Google counts
them, in Redis under the Pacific date, so separate runs on one day add up. Calls made
outside the judge (the API's match sentences) are not counted here: the margin is for
them.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

PACIFIC = ZoneInfo("America/Los_Angeles")
IST = ZoneInfo("Asia/Kolkata")
# Requests a judge run may spend per provider per Pacific day (None: no daily cap).
DAILY_REQUESTS: dict[str, int | None] = {"gemini": 480, "groq": None}
# Calls a minute when --rpm is not given (0: paced by tokens only). Gemini's free tier
# allows 15 a minute (its 429 names GenerateRequestsPerMinutePerProjectPerModel-FreeTier,
# 15, seen 2026-11-26 at 20 a minute); the judge halves its pace after a 429 anyway.
REQUESTS_PER_MINUTE: dict[str, float] = {"gemini": 15.0, "groq": 0.0}


def pacific_day(now: datetime) -> str:
    return now.astimezone(PACIFIC).date().isoformat()


def next_reset(now: datetime) -> datetime:
    """The next midnight Pacific, as an aware datetime."""
    local = now.astimezone(PACIFIC)
    midnight = datetime(local.year, local.month, local.day, tzinfo=PACIFIC) + timedelta(days=1)
    return midnight.astimezone(UTC)


def resume_message(now: datetime) -> str:
    reset = next_reset(now)
    return (
        f"resume after {reset.astimezone(IST):%Y-%m-%d %H:%M} IST "
        f"(midnight Pacific, {reset:%H:%M} UTC)"
    )


@dataclass
class DailyBudget:
    """A per-provider, per-Pacific-day request counter in Redis."""

    redis: Redis
    provider: str
    limit: int

    def _key(self, now: datetime) -> str:
        return f"llm:requests:{self.provider}:{pacific_day(now)}"

    async def used(self, now: datetime) -> int:
        value = await self.redis.get(self._key(now))
        return int(value) if value else 0

    async def add(self, n: int, now: datetime) -> int:
        if n <= 0:
            return await self.used(now)
        key = self._key(now)
        total = int(await self.redis.incrby(key, n))
        await self.redis.expire(key, 3 * 24 * 3600)
        return total
