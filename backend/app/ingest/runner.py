"""One ingestion run: fetch every source, store, expire, flag stale, dedup, embed."""

import asyncio
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.ingest.companies import CompanyEntry, company_for_name, sync_companies
from app.ingest.dedup import deduplicate
from app.ingest.embed import Embedder, embed_pending, pending_by_source
from app.ingest.normalise import NormalisedJob, normalise
from app.ingest.sources.ashby import AshbyAdapter
from app.ingest.sources.base import USER_AGENT, Adapter, SourceError
from app.ingest.sources.greenhouse import GreenhouseAdapter
from app.ingest.sources.lever import LeverAdapter
from app.ingest.sources.remotive import BOARD as REMOTIVE_BOARD
from app.ingest.sources.remotive import RemotiveAdapter
from app.ingest.store import mark_stale, record_misses, upsert_jobs
from app.ingest.types import BoardResult
from app.models import Company, IngestRun

logger = logging.getLogger(__name__)

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "remotive": RemotiveAdapter(),
}
ALL_SOURCES = tuple(ADAPTERS)


# A run that has said "running" for longer than this died without finishing.
INTERRUPTED_AFTER = timedelta(hours=6)


@dataclass
class RunSummary:
    run_id: uuid.UUID
    sources: dict[str, IngestRun] = field(default_factory=dict)
    stale: int = 0
    duplicates: dict[str, int] = field(default_factory=dict)
    embedded: int = 0
    errors: list[str] = field(default_factory=list)
    seconds: float = 0.0


async def run_ingest(
    sessionmaker: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    embedder: Embedder,
    companies: list[CompanyEntry],
    settings: Settings,
    *,
    sources: Sequence[str] = ALL_SOURCES,
    adapters: Mapping[str, Adapter] | None = None,
    now: datetime | None = None,
) -> RunSummary:
    """Fetch and store each source, then (once, for the whole pool) mark stale jobs,
    embed what is pending and dedup. Each source's ingest_runs row is finished only
    after all stages, so its status covers its jobs' embeddings too."""
    started = time.perf_counter()
    now = now or datetime.now(UTC)
    adapters = adapters or ADAPTERS
    summary = RunSummary(run_id=uuid.uuid4())
    logger.info(
        "ingest run started", extra={"run_id": str(summary.run_id), "sources": list(sources)}
    )

    async with sessionmaker() as session:
        await _mark_interrupted_runs(session, now)
        by_token = await sync_companies(session, companies)
        await session.commit()

    for source in sources:
        summary.sources[source] = await _run_source(
            sessionmaker, http, adapters[source], source, by_token, settings, summary.run_id, now
        )

    embedded_by_source: dict[str, int] = {}
    async with sessionmaker() as session:
        stage = "stale"
        try:
            summary.stale = await mark_stale(session, now, settings.ingest_stale_after_days)
            await session.commit()
            stage = "embed"
            summary.embedded = await embed_pending(session, embedder, embedded_by_source)
            stage = "dedup"
            summary.duplicates = await deduplicate(
                session, settings.ingest_near_duplicate_threshold
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            summary.embedded = sum(embedded_by_source.values())
            summary.errors.append(f"{stage}: {exc!r}"[:1000])
            logger.exception("ingest stage failed", extra={"stage": stage})
        pending = await pending_by_source(session)

    async with sessionmaker() as session:
        for source, run in summary.sources.items():
            summary.sources[source] = await _finish(
                session,
                run,
                embedded_by_source.get(source, 0),
                pending.get(source, 0),
                summary.errors,
            )
        await session.commit()

    summary.seconds = round(time.perf_counter() - started, 1)
    logger.info(
        "ingest run finished",
        extra={
            "run_id": str(summary.run_id),
            "seconds": summary.seconds,
            "stale": summary.stale,
            "embedded": summary.embedded,
            "duplicates": summary.duplicates,
            "statuses": {s: r.status for s, r in summary.sources.items()},
            "errors": summary.errors,
        },
    )
    return summary


async def _finish(
    session: AsyncSession,
    run: IngestRun,
    embedded: int,
    pending: int,
    stage_errors: list[str],
) -> IngestRun:
    run = await session.merge(run)
    run.finished_at = datetime.now(UTC)
    if run.status in ("skipped", "failed"):
        return run  # decided in the fetch/store stage; later stages did not touch it
    run.embedded, run.embed_pending = embedded, pending
    problems: list[str] = []
    if run.boards_failed:
        problems.append(f"fetch: {run.boards_failed} boards failed")
    if run.skipped:
        problems.append(f"normalise: {run.skipped} postings skipped")
    if pending:
        problems.append(f"embed: {pending} jobs still without an embedding")
    problems.extend(stage_errors)
    run.status = "partial" if problems else "succeeded"
    run.error = "; ".join(problems)[:1000] or None
    return run


async def _mark_interrupted_runs(session: AsyncSession, now: datetime) -> None:
    """A row left "running" by a process that died is failed, not running forever."""
    await session.execute(
        update(IngestRun)
        .where(IngestRun.status == "running", IngestRun.started_at < now - INTERRUPTED_AFTER)
        .values(
            status="failed",
            error="interrupted: the run stopped without recording completion",
            finished_at=now,
        )
    )


async def _run_source(
    sessionmaker: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    adapter: Adapter,
    source: str,
    by_token: dict[str, Company],
    settings: Settings,
    run_id: uuid.UUID,
    now: datetime,
) -> IngestRun:
    """Fetch and store one source. The row is committed as "running" first, so a crash
    leaves evidence; run_ingest finishes it after the embed and dedup stages."""
    async with sessionmaker() as session:
        run = IngestRun(
            run_id=run_id,
            source=source,
            started_at=now,
            status="running",
            boards_ok=0,
            boards_failed=0,
            fetched=0,
            new=0,
            updated=0,
            unchanged=0,
            expired=0,
            skipped=0,
            failures=[],
        )
        session.add(run)
        await session.commit()

        if source == "remotive" and (note := await _remotive_too_soon(session, settings, now)):
            run.status, run.note = "skipped", note
            await session.commit()
            logger.info("source skipped", extra={"source": source, "note": note})
            return run

        try:
            await _fetch_and_store(session, http, adapter, source, by_token, settings, run, now)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            run = await session.merge(run)
            run.status = "failed"
            run.error = f"store: {exc!r}"[:1000]
            await session.commit()
            logger.exception("source failed", extra={"source": source})
            return run

    logger.info(
        "source ingested",
        extra={
            "source": source,
            "status": run.status,
            "boards_ok": run.boards_ok,
            "boards_failed": run.boards_failed,
            "fetched": run.fetched,
            "new": run.new,
            "updated": run.updated,
            "unchanged": run.unchanged,
            "expired": run.expired,
            "skipped": run.skipped,
        },
    )
    return run


async def _fetch_and_store(
    session: AsyncSession,
    http: httpx.AsyncClient,
    adapter: Adapter,
    source: str,
    by_token: dict[str, Company],
    settings: Settings,
    run: IngestRun,
    now: datetime,
) -> None:
    boards: list[tuple[str, Company | None]] = (
        [(REMOTIVE_BOARD, None)]
        if source == "remotive"
        else [(token, c) for token, c in by_token.items() if c.ats == source]
    )
    results = await _fetch_all(http, adapter, boards, settings.ingest_concurrency)

    ok_company_ids: list[uuid.UUID] = []
    failures: list[dict[str, str]] = []
    to_store: list[tuple[NormalisedJob, uuid.UUID]] = []
    for (board, company), result in zip(boards, results, strict=True):
        if isinstance(result, SourceError):
            failures.append({"board": board, "error": str(result)})
            continue
        run.boards_ok += 1
        if company is not None:
            ok_company_ids.append(company.id)
        run.fetched += len(result.postings)
        for posting in result.postings:
            try:
                job = normalise(posting)
            except Exception as exc:  # one bad posting must not sink the board
                run.skipped += 1
                failures.append(
                    {"board": board, "error": f"posting {posting.source_id}: {exc!r}"[:300]}
                )
                continue
            owner = company or await company_for_name(session, job.company_name)
            to_store.append((job, owner.id))

    counts, seen = await upsert_jobs(session, to_store, now)
    run.new, run.updated, run.unchanged = counts.new, counts.updated, counts.unchanged
    if run.boards_ok:
        run.expired = await record_misses(
            session,
            source,
            seen,
            None if source == "remotive" else ok_company_ids,
            settings.ingest_expire_after_missed_runs,
        )
    run.boards_failed = sum(1 for f in failures if not f["error"].startswith("posting "))
    run.failures = failures
    if run.boards_ok == 0:
        run.status = "failed"
        run.error = "fetch: no board could be fetched"


async def _fetch_all(
    http: httpx.AsyncClient,
    adapter: Adapter,
    boards: list[tuple[str, Company | None]],
    concurrency: int,
) -> list[BoardResult | SourceError]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(board: str, company: Company | None) -> BoardResult | SourceError:
        async with semaphore:
            try:
                return await adapter.fetch(http, board, company.name if company else "")
            except SourceError as exc:
                return exc

    return await asyncio.gather(*(one(board, company) for board, company in boards))


async def _remotive_too_soon(
    session: AsyncSession, settings: Settings, now: datetime
) -> str | None:
    """Remotive asks for at most 4 fetches a day."""
    last = await session.scalar(
        select(IngestRun.started_at)
        .where(
            IngestRun.source == "remotive",
            IngestRun.status.in_(("succeeded", "partial")),
        )
        .order_by(IngestRun.started_at.desc())
        .limit(1)
    )
    interval = timedelta(hours=settings.remotive_min_interval_hours)
    if last is not None and now - last < interval:
        return f"last fetched {last.isoformat()}; Remotive allows one fetch per {interval}"
    return None


def build_http_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=httpx.Timeout(settings.ingest_http_timeout_seconds),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=settings.ingest_concurrency * 2),
    )
