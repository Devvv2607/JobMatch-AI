"""One ingest (or re-embed) at a time, across every process: a Redis lock with a TTL.

Taken with SET NX and a random token; refreshed every TTL/3 while the run is alive, so a
long first embed never outlives it, and released only by its owner (compare-and-delete).
If the process dies, the lock expires after at most one TTL. If Redis is unreachable the
run does not start: running twice is worse than running late.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable
from typing import cast

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

LOCK_KEY = "lock:ingest"

_REFRESH = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class IngestLockedError(Exception):
    """Another ingest or re-embed holds the lock."""


@contextlib.asynccontextmanager
async def ingest_lock(redis: Redis, ttl_seconds: int, what: str) -> AsyncIterator[None]:
    token = f"{what}:{uuid.uuid4().hex}"
    if not await redis.set(LOCK_KEY, token, nx=True, ex=ttl_seconds):
        holder = await redis.get(LOCK_KEY)
        holder = holder.decode() if isinstance(holder, bytes) else holder
        raise IngestLockedError(f"another run holds the ingest lock ({holder})")

    async def refresh() -> None:
        while True:
            await asyncio.sleep(ttl_seconds / 3)
            refreshed = redis.eval(_REFRESH, 1, LOCK_KEY, token, str(ttl_seconds))
            if not await cast(Awaitable[int], refreshed):
                logger.error("ingest lock lost while running", extra={"what": what})
                return

    refresher = asyncio.create_task(refresh())
    logger.info("ingest lock acquired", extra={"what": what})
    try:
        yield
    finally:
        refresher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await refresher
        await cast(Awaitable[int], redis.eval(_RELEASE, 1, LOCK_KEY, token))
        logger.info("ingest lock released", extra={"what": what})


async def lock_holder(redis: Redis) -> str | None:
    value = await redis.get(LOCK_KEY)
    return value.decode() if isinstance(value, bytes) else value
