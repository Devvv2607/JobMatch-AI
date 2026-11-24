"""How current the pool is: the last successful ingest and what the last run changed.

Read by the API (`GET /api/v1/jobs/freshness`, `pool.updated_at` in search responses,
for an "Updated 3 hours ago" label), by `/metrics`, and by the worker's catch-up check.
"""

import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import INGEST_LAST_RUN_JOBS, INGEST_LAST_SUCCESS

# A run counts as successful when at least one source finished `succeeded` or `partial`
# (some boards failed but the rest were stored, embedded and indexed).
_SQL = text(
    """
    WITH last_run AS (
        SELECT run_id FROM ingest_runs ORDER BY started_at DESC LIMIT 1
    )
    SELECT
        (SELECT max(finished_at) FROM ingest_runs
          WHERE status IN ('succeeded', 'partial')) AS last_success_at,
        max(r.finished_at) AS last_run_finished_at,
        min(r.started_at) AS last_run_started_at,
        coalesce(sum(r.new), 0) AS added,
        coalesce(sum(r.updated), 0) AS updated,
        coalesce(sum(r.expired), 0) AS expired,
        string_agg(DISTINCT r.status, ',' ORDER BY r.status) AS statuses
    FROM ingest_runs r JOIN last_run USING (run_id)
    """
)


@dataclass(frozen=True)
class Freshness:
    last_success_at: datetime | None
    last_run_started_at: datetime | None
    last_run_finished_at: datetime | None
    last_run_statuses: list[str]
    added: int
    updated: int
    expired: int


async def freshness(session: AsyncSession) -> Freshness:
    # An aggregate always returns one row; with no runs its values are NULL / 0.
    row = (await session.execute(_SQL)).mappings().one()
    return Freshness(
        last_success_at=row["last_success_at"],
        last_run_started_at=row["last_run_started_at"],
        last_run_finished_at=row["last_run_finished_at"],
        last_run_statuses=(row["statuses"] or "").split(",") if row["statuses"] else [],
        added=int(row["added"]),
        updated=int(row["updated"]),
        expired=int(row["expired"]),
    )


_cache: tuple[float, Freshness] | None = None


async def cached_freshness(session: AsyncSession, max_age_seconds: float = 30) -> Freshness:
    """Per process, at most one query every `max_age_seconds`; also updates the gauges."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < max_age_seconds:
        return _cache[1]
    value = await freshness(session)
    _cache = (now, value)
    if value.last_success_at is not None:
        INGEST_LAST_SUCCESS.set(value.last_success_at.timestamp())
    for change, count in (
        ("added", value.added),
        ("updated", value.updated),
        ("expired", value.expired),
    ):
        INGEST_LAST_RUN_JOBS.labels(change).set(count)
    return value


def reset_cache() -> None:
    global _cache
    _cache = None
