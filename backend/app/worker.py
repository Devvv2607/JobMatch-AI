"""arq worker. Run with: arq app.worker.WorkerSettings

Keeps the pool fresh without anyone running a command:
- a daily ingest at INGEST_CRON_HOURS:INGEST_CRON_MINUTE in INGEST_CRON_TIMEZONE
  (default 03:00 Asia/Kolkata), which also embeds what changed and rebuilds BM25;
- on start, if the last successful ingest is older than INGEST_CATCHUP_AFTER_HOURS (or
  there is none), one catch-up ingest is enqueued under a fixed job id, so restarts
  cannot stack several;
- every ingest holds the Redis ingest lock (app/ingest/lock.py), so the cron, a
  catch-up and a manual `make ingest` never overlap.

The worker loads the embedding model (lazily, on the first ingest) and never the
cross-encoder; only the API reranks.
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from arq import ArqRedis, cron
from arq.connections import RedisSettings
from arq.cron import CronJob

from app.auth.service import purge_expired_refresh_tokens
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal, engine
from app.core.logging import configure_logging
from app.core.redis import redis
from app.ingest.freshness import freshness
from app.ingest.lock import IngestLockedError, ingest_lock, lock_holder

logger = logging.getLogger(__name__)

CATCHUP_JOB_ID = "ingest:catchup"


async def purge_refresh_tokens(ctx: dict[Any, Any]) -> int:
    """Deletes refresh tokens past their expiry. Idempotent."""
    async with SessionLocal() as session:
        deleted = await purge_expired_refresh_tokens(session)
        await session.commit()
    logger.info("purged expired refresh tokens", extra={"deleted": deleted})
    return deleted


async def ingest_jobs(ctx: dict[Any, Any]) -> dict[str, Any]:
    """Ingestion of every source. Safe to re-run: upserts are keyed on (source, source_id)
    and every later pass is recomputed from the table. Skipped if another run holds the
    ingest lock."""
    from app.ingest.companies import load_companies
    from app.ingest.runner import build_http_client, run_ingest
    from app.ml.embedder import OnnxEmbedder

    settings = get_settings()
    try:
        async with ingest_lock(redis, settings.ingest_lock_ttl_seconds, "worker ingest"):
            if "embedder" not in ctx:
                ctx["embedder"] = OnnxEmbedder(
                    Path(settings.embedding_model_dir),
                    settings.embedding_model_file,
                    settings.embedding_threads,
                )
            async with build_http_client(settings) as http:
                summary = await run_ingest(
                    SessionLocal, http, ctx["embedder"], load_companies(), settings
                )
    except IngestLockedError as exc:
        logger.warning("scheduled ingest skipped", extra={"reason": str(exc)})
        return {"skipped": str(exc)}
    return {"run_id": str(summary.run_id), "seconds": summary.seconds, "embedded": summary.embedded}


async def enqueue_catchup_if_stale(
    pool: ArqRedis, settings: Settings, now: datetime | None = None
) -> str:
    """Enqueues one ingest when the pool is stale. Returns what it did, for the log."""
    now = now or datetime.now(UTC)
    async with SessionLocal() as session:
        last = (await freshness(session)).last_success_at
    max_age = timedelta(hours=settings.ingest_catchup_after_hours)
    if last is not None and now - last < max_age:
        return f"fresh (last success {last.isoformat()})"
    if holder := await lock_holder(redis):
        return f"stale, but a run is in progress ({holder})"
    job = await pool.enqueue_job("ingest_jobs", _job_id=CATCHUP_JOB_ID)
    if job is None:  # arq refuses a second job with the same id while one exists
        return "stale, catch-up already queued"
    return f"stale (last success {last.isoformat() if last else 'never'}), catch-up enqueued"


def cron_jobs(settings: Settings) -> list[CronJob]:
    jobs = [cron(purge_refresh_tokens, hour=3, minute=0, run_at_startup=True)]
    if settings.ingest_cron_enabled:
        jobs.append(
            cron(
                ingest_jobs,
                hour=settings.ingest_cron_hour_set,
                minute=settings.ingest_cron_minute,
                timeout=3 * 3600,
                unique=True,
            )
        )
    return jobs


async def startup(ctx: dict[Any, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "worker started",
        extra={
            "ingest_cron_enabled": settings.ingest_cron_enabled,
            "ingest_cron": f"{settings.ingest_cron_hours}:{settings.ingest_cron_minute:02d} "
            f"{settings.ingest_cron_timezone}",
        },
    )
    if settings.ingest_cron_enabled:
        outcome = await enqueue_catchup_if_stale(ctx["redis"], settings)
        logger.info("ingest catch-up check", extra={"outcome": outcome})


async def shutdown(ctx: dict[Any, Any]) -> None:
    await engine.dispose()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Enqueue-able by name (the catch-up); the cron entry below schedules the same task.
    functions: ClassVar = [ingest_jobs]
    cron_jobs: ClassVar = cron_jobs(get_settings())
    # Cron hours are read in this zone (the purge at 03:00 too).
    timezone = ZoneInfo(get_settings().ingest_cron_timezone)
    on_startup = startup
    on_shutdown = shutdown
    health_check_interval = 30
    # A first full embed of ~12k jobs takes about an hour; the cron job sets its own.
    job_timeout = 3 * 3600
