import logging
import os
from typing import Literal

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess
from pydantic import BaseModel
from sqlalchemy import text

from app.core.db import engine
from app.core.redis import redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ops"])


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, bool]


@router.get("/healthz")
async def healthz() -> Health:
    """Liveness: the process is up. Touches no dependencies."""
    return Health()


@router.get("/readyz", responses={503: {"model": Readiness}})
async def readyz(response: Response) -> Readiness:
    """Readiness: Postgres and Redis both answer."""
    checks = {"database": await _database_ok(), "redis": await _redis_ok()}
    ready = all(checks.values())
    if not ready:
        response.status_code = 503
    return Readiness(status="ready" if ready else "not_ready", checks=checks)


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """With several uvicorn workers (API_WORKERS > 1) each process keeps its own
    counters; PROMETHEUS_MULTIPROC_DIR makes them write to files that are summed here,
    so a scrape sees every worker, not whichever one answered it."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def _database_ok() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("readiness: database check failed", exc_info=True)
        return False


async def _redis_ok() -> bool:
    try:
        return bool(await redis.ping())
    except Exception:
        logger.warning("readiness: redis check failed", exc_info=True)
        return False
