"""Rate limiting in Redis.

Two shapes:
- `enforce_rate_limit`: a fixed window that counts every request (per IP, per token
  family, per user).
- `ensure_not_locked_out` / `record_failure`: counts failures only, in a window that
  starts at the first failure, so successful requests never use up the allowance.

If Redis is unreachable the limiter fails open and logs: locking every user out of
login because the cache is down is worse than briefly not limiting.
"""

import hashlib
import logging
import time

from redis.exceptions import RedisError

from app.core.errors import RateLimitedError
from app.core.redis import redis

logger = logging.getLogger(__name__)

# One message for every limit, so a 429 never reveals which limit applied or whether
# an email address has an account.
_MESSAGE = "Too many requests. Try again shortly."


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
        raise RateLimitedError(_MESSAGE, headers={"Retry-After": str(retry_after)})


async def ensure_not_locked_out(bucket: str, subject: str, max_failures: int) -> None:
    """Raises 429 if `subject` already has `max_failures` failures in the current window."""
    key = _failure_key(bucket, subject)
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.get(key)
            pipe.ttl(key)
            count, ttl = await pipe.execute()
    except RedisError:
        logger.error("lockout check unavailable, failing open", extra={"bucket": bucket})
        return
    if count is not None and int(count) >= max_failures:
        raise RateLimitedError(_MESSAGE, headers={"Retry-After": str(max(int(ttl), 1))})


async def record_failure(bucket: str, subject: str, window_seconds: int) -> None:
    """Counts one failure. The window starts at the first failure and is not extended."""
    key = _failure_key(bucket, subject)
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            await pipe.execute()
    except RedisError:
        logger.error("failure counter unavailable", extra={"bucket": bucket})


def _failure_key(bucket: str, subject: str) -> str:
    # Hashed so email addresses are not stored in Redis in the clear.
    digest = hashlib.sha256(subject.encode()).hexdigest()
    return f"fail:{bucket}:{digest}"
