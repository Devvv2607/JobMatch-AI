"""Writing normalised postings to the jobs table: new, updated, unchanged, missed, expired,
stale. Every function here is idempotent for the same input and time."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.normalise import NormalisedJob
from app.models import Job


@dataclass
class UpsertCounts:
    new: int = 0
    updated: int = 0
    unchanged: int = 0


def _fields(job: NormalisedJob, company_id: uuid.UUID) -> dict[str, object]:
    salary = job.salary
    return {
        "company_id": company_id,
        "title": job.title,
        "title_norm": job.title_norm,
        "location": job.location,
        "location_norm": job.location_norm,
        "remote_policy": job.remote_policy,
        "employment_type": job.employment_type,
        "seniority": job.seniority,
        "work_countries": list(job.work.countries),
        "eligibility_scope": job.work.scope,
        "eligibility_source": job.work.source[:64],
        "salary_min": salary.min if salary else None,
        "salary_max": salary.max if salary else None,
        "salary_currency": salary.currency if salary else None,
        "salary_interval": salary.interval if salary else None,
        "salary_min_usd": salary.min_usd if salary else None,
        "salary_max_usd": salary.max_usd if salary else None,
        "salary_source": salary.source if salary else None,
        "description": job.description,
        "skills": job.skills,
        "source_url": job.source_url,
        "posted_at": job.posted_at,
        "content_hash": job.content_hash,
    }


async def upsert_jobs(
    session: AsyncSession,
    jobs: list[tuple[NormalisedJob, uuid.UUID]],
    now: datetime,
) -> tuple[UpsertCounts, set[uuid.UUID]]:
    """Inserts new postings and updates known ones. Returns counts and the ids seen."""
    counts = UpsertCounts()
    seen: set[uuid.UUID] = set()
    if not jobs:
        return counts, seen
    source = jobs[0][0].source
    ids = [job.source_id for job, _ in jobs]
    existing = {
        row.source_id: row
        for row in await session.scalars(
            select(Job).where(Job.source == source, Job.source_id.in_(ids))
        )
    }
    for job, company_id in jobs:
        row = existing.get(job.source_id)
        if row is None:
            row = Job(
                id=uuid.uuid4(),
                source=job.source,
                source_id=job.source_id,
                first_seen_at=now,
                last_seen_at=now,
                content_changed_at=now,
                status="live",
                missed_runs=0,
                **_fields(job, company_id),
            )
            session.add(row)
            existing[job.source_id] = row
            counts.new += 1
        elif row.content_hash != job.content_hash:
            for name, value in _fields(job, company_id).items():
                setattr(row, name, value)
            row.status = "updated"
            row.content_changed_at = now
            row.last_seen_at = now
            row.missed_runs = 0
            counts.updated += 1
        else:
            # Seen again unchanged: a returning expired job is live again; "updated"
            # lasts one run. "stale" is left for the freshness pass to decide.
            if row.status in ("expired", "updated"):
                row.status = "live"
            row.last_seen_at = now
            row.missed_runs = 0
            counts.unchanged += 1
        seen.add(row.id)
    await session.flush()
    return counts, seen


async def record_misses(
    session: AsyncSession,
    source: str,
    seen: set[uuid.UUID],
    company_ids: list[uuid.UUID] | None,
    expire_after: int,
) -> int:
    """Counts a miss for every non-expired job of `source` that was not seen, limited to
    boards that were fetched successfully (a failed fetch is not evidence a job is gone).
    Returns how many jobs became expired."""
    scope = [Job.source == source, Job.status != "expired"]
    if company_ids is not None:
        if not company_ids:
            return 0
        scope.append(Job.company_id.in_(company_ids))
    if seen:
        scope.append(Job.id.not_in(seen))
    await session.execute(update(Job).where(*scope).values(missed_runs=Job.missed_runs + 1))
    result = await session.execute(
        update(Job)
        .where(*scope, Job.missed_runs >= expire_after)
        .values(status="expired")
        .returning(Job.id)
    )
    return len(result.all())


async def mark_stale(session: AsyncSession, now: datetime, stale_after_days: int) -> int:
    """Live or updated jobs older than the threshold whose content has not changed within
    it become stale (possible ghost listings). Returns how many changed."""
    cutoff = now - timedelta(days=stale_after_days)
    age_from = Job.posted_at.is_not(None)
    old = or_(and_(age_from, Job.posted_at < cutoff), and_(~age_from, Job.first_seen_at < cutoff))
    result = await session.execute(
        update(Job)
        .where(Job.status.in_(("live", "updated")), old, Job.content_changed_at < cutoff)
        .values(status="stale")
        .returning(Job.id)
    )
    return len(result.all())
