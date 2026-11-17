"""arq worker. Run with: arq app.worker.WorkerSettings

The worker never loads the cross-encoder; only the API reranks.
"""

import logging
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.auth.service import purge_expired_refresh_tokens
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


async def purge_refresh_tokens(ctx: dict[Any, Any]) -> int:
    """Deletes refresh tokens past their expiry. Idempotent."""
    async with SessionLocal() as session:
        deleted = await purge_expired_refresh_tokens(session)
        await session.commit()
    logger.info("purged expired refresh tokens", extra={"deleted": deleted})
    return deleted


async def startup(ctx: dict[Any, Any]) -> None:
    configure_logging(get_settings().log_level)
    logger.info("worker started")


async def shutdown(ctx: dict[Any, Any]) -> None:
    await engine.dispose()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    cron_jobs: ClassVar = [cron(purge_refresh_tokens, hour=3, minute=0, run_at_startup=True)]
    on_startup = startup
    on_shutdown = shutdown
    health_check_interval = 30
    job_timeout = 600
