"""Keeping the pool fresh: catch-up on worker start, the ingest lock, freshness numbers,
and the posted-within-days dealbreaker."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import redis
from app.ingest.freshness import freshness, reset_cache
from app.ingest.lock import LOCK_KEY, IngestLockedError, ingest_lock
from app.models import IngestRun
from app.retrieval.filters import allowed_ids, outcomes
from app.retrieval.rules import PostedWithinDays
from app.worker import CATCHUP_JOB_ID, enqueue_catchup_if_stale
from tests.helpers import bearer, register
from tests.search_helpers import add_company, add_job

NOW = datetime(2026, 11, 24, 6, 0, tzinfo=UTC)


@pytest.fixture
async def pool() -> AsyncIterator[ArqRedis]:
    arq = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    yield arq
    await arq.aclose()


async def add_run(
    session: AsyncSession, finished: datetime | None, status: str, **counts: int
) -> uuid.UUID:
    run_id = uuid.uuid4()
    for source in ("greenhouse", "lever"):
        session.add(
            IngestRun(
                run_id=run_id,
                source=source,
                started_at=(finished or NOW) - timedelta(minutes=5),
                finished_at=finished,
                status=status,
                new=counts.get("new", 0),
                updated=counts.get("updated", 0),
                expired=counts.get("expired", 0),
            )
        )
    await session.commit()
    return run_id


async def queued(arq: ArqRedis) -> list[str]:
    return [job.job_id for job in await arq.queued_jobs() if job.job_id is not None]


async def test_a_stale_pool_enqueues_exactly_one_catch_up(
    session: AsyncSession, pool: ArqRedis
) -> None:
    await add_run(session, NOW - timedelta(hours=30), "succeeded")
    first = await enqueue_catchup_if_stale(pool, get_settings(), NOW)
    second = await enqueue_catchup_if_stale(pool, get_settings(), NOW)  # e.g. a restart
    assert "enqueued" in first and "already queued" in second
    assert await queued(pool) == [CATCHUP_JOB_ID]


async def test_no_successful_ingest_at_all_counts_as_stale(
    session: AsyncSession, pool: ArqRedis
) -> None:
    await add_run(session, NOW - timedelta(hours=1), "failed")
    assert "never" in await enqueue_catchup_if_stale(pool, get_settings(), NOW)
    assert await queued(pool) == [CATCHUP_JOB_ID]


async def test_a_fresh_pool_enqueues_nothing(session: AsyncSession, pool: ArqRedis) -> None:
    await add_run(session, NOW - timedelta(hours=30), "succeeded")
    await add_run(session, NOW - timedelta(hours=2), "partial")  # partial still counts
    assert (await enqueue_catchup_if_stale(pool, get_settings(), NOW)).startswith("fresh")
    assert await queued(pool) == []


async def test_a_stale_pool_with_a_run_in_progress_enqueues_nothing(
    session: AsyncSession, pool: ArqRedis
) -> None:
    await add_run(session, NOW - timedelta(hours=30), "succeeded")
    async with ingest_lock(redis, 60, "cli run"):
        outcome = await enqueue_catchup_if_stale(pool, get_settings(), NOW)
    assert "in progress (cli run:" in outcome
    assert await queued(pool) == []


async def test_concurrent_triggers_are_blocked_by_the_lock() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def first() -> None:
        async with ingest_lock(redis, 60, "worker ingest"):
            started.set()
            await release.wait()

    holder = asyncio.create_task(first())
    await started.wait()
    with pytest.raises(IngestLockedError, match="worker ingest"):
        async with ingest_lock(redis, 60, "cli run"):
            pytest.fail("a second run must not start")
    release.set()
    await holder
    assert await redis.get(LOCK_KEY) is None  # released
    async with ingest_lock(redis, 60, "cli run"):  # and free again
        pass


async def test_the_lock_is_refreshed_while_held_and_only_the_owner_releases_it() -> None:
    async with ingest_lock(redis, 3, "long run"):
        await asyncio.sleep(4)  # longer than the TTL: refreshed every second
        assert await redis.get(LOCK_KEY) is not None
        await redis.set(LOCK_KEY, "someone-else")  # e.g. after expiry and a new run
    assert await redis.get(LOCK_KEY) in (b"someone-else", "someone-else")


async def test_freshness_reports_the_last_success_and_the_last_runs_changes(
    session: AsyncSession,
) -> None:
    assert (await freshness(session)).last_success_at is None
    await add_run(session, NOW - timedelta(days=1), "succeeded", new=5)
    await add_run(session, NOW - timedelta(hours=1), "failed", new=1, updated=2, expired=3)
    f = await freshness(session)
    assert f.last_success_at == NOW - timedelta(days=1)
    assert (f.added, f.updated, f.expired) == (2, 4, 6)  # two sources in the last run
    assert f.last_run_statuses == ["failed"]


async def test_freshness_endpoint_and_metrics(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    reset_cache()
    await add_run(session, NOW, "succeeded", new=7, updated=1, expired=2)
    assert (await client.get("/api/v1/jobs/freshness")).status_code == 401
    auth = bearer(await register(client, "fresh@example.com"))
    body = (await client.get("/api/v1/jobs/freshness", headers=auth)).json()
    assert body["updated_at"].startswith("2026-11-24T06:00:00")
    assert body["last_run"]["added"] == 14 and body["last_run"]["expired"] == 4
    metrics = (await client.get("/metrics")).text
    line = next(x for x in metrics.splitlines() if x.startswith("ingest_last_success_timestamp"))
    assert float(line.split()[-1]) == NOW.timestamp()
    assert 'ingest_last_run_jobs{change="added"} 14.0' in metrics
    reset_cache()


async def test_posted_within_days_rule(session: AsyncSession) -> None:
    company = await add_company(session, "Fresh Co")
    now = datetime.now(UTC)
    recent = await add_job(session, company, "New", posted_at=now - timedelta(days=2))
    old = await add_job(session, company, "Old", posted_at=now - timedelta(days=30))
    undated = await add_job(session, company, "Undated", posted_at=None)
    await session.commit()

    rule = PostedWithinDays(days=7)
    assert set(await allowed_ids(session, [rule])) == {recent.id, undated.id}
    assert set(await allowed_ids(session, [PostedWithinDays(days=7, strict=True)])) == {recent.id}
    labels = await outcomes(session, [rule], [recent.id, old.id, undated.id])
    assert [labels[i][0].outcome for i in (recent.id, old.id, undated.id)] == [
        "pass",
        "violates",
        "unknown",
    ]
    assert rule.describe() == "Posted in the last 7 days"
