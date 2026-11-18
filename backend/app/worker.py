"""arq worker. Run with: arq app.worker.WorkerSettings

The worker loads the embedding model (lazily, on the first ingest) and never the
cross-encoder; only the API reranks.
"""

import logging
from pathlib import Path
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob

from app.auth.service import purge_expired_refresh_tokens
from app.core.config import Settings, get_settings
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


async def ingest_jobs(ctx: dict[Any, Any]) -> dict[str, Any]:
    """Scheduled ingestion of every source. Safe to re-run: upserts are keyed on
    (source, source_id) and every later pass is recomputed from the table."""
    from app.ingest.companies import load_companies
    from app.ingest.runner import build_http_client, run_ingest
    from app.ml.embedder import OnnxEmbedder

    settings = get_settings()
    if "embedder" not in ctx:
        ctx["embedder"] = OnnxEmbedder(
            Path(settings.embedding_model_dir),
            settings.embedding_model_file,
            settings.embedding_threads,
        )
    async with build_http_client(settings) as http:
        summary = await run_ingest(SessionLocal, http, ctx["embedder"], load_companies(), settings)
    return {"run_id": str(summary.run_id), "seconds": summary.seconds, "embedded": summary.embedded}


def cron_jobs(settings: Settings) -> list[CronJob]:
    jobs = [cron(purge_refresh_tokens, hour=3, minute=0, run_at_startup=True)]
    if settings.ingest_cron_enabled:
        jobs.append(
            cron(
                ingest_jobs,
                hour=settings.ingest_cron_hour_set,
                minute=10,
                timeout=3600,
                unique=True,
            )
        )
    return jobs


async def startup(ctx: dict[Any, Any]) -> None:
    configure_logging(get_settings().log_level)
    logger.info("worker started", extra={"ingest_cron_enabled": get_settings().ingest_cron_enabled})


async def shutdown(ctx: dict[Any, Any]) -> None:
    await engine.dispose()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    cron_jobs: ClassVar = cron_jobs(get_settings())
    on_startup = startup
    on_shutdown = shutdown
    health_check_interval = 30
    job_timeout = 600
