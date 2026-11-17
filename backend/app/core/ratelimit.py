"""Fixed-window rate limiting in Redis.

If Redis is unreachable the limiter fails open and logs: locking every user out of
login because the cache is down is worse than briefly not limiting.
"""

import logging
import time

from redis.exceptions import RedisError

from app.core.errors import RateLimitedError
from app.core.redis import redis

logger = logging.getLogger(__name__)


async def enforce_rate_limit(bucket: str, client_key: str, limit: int, window_seconds: int) -> None:
    window = int(time.time()) // window_seconds
    key = f"rl:{bucket}:{client_key}:{window}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds * 2)
            count, _ = await pipe.execute()
    except RedisError:
        logger.error("rate limiter unavailable, failing open", extra={"bucket": bucket})
        return
    if count > limit:
        retry_after = window_seconds - int(time.time()) % window_seconds
        raise RateLimitedError(
            "Too many requests. Try again shortly.", headers={"Retry-After": str(retry_after)}
        )
