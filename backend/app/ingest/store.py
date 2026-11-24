"""Writing normalised postings to the jobs table: new, updated, unchanged, missed, expired,
stale. Every function here is idempotent for the same input and time."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.normalise import NormalisedJob
from app.models import Job


@dataclass
class UpsertCounts:
    new: int = 0
    updated: int = 0
    unchanged: int = 0


# Fields that are derived from the posting by rules (eligibility, skills, seniority,
# salary parsing) rather than being its content. They are rewritten even when the content
# hash is unchanged, so a rule change (say, a new place in locations.yaml) reaches every
# job on the next run without waiting for the posting to change.
_DERIVED = (
    "company_id",
    "title_norm",
    "location_norm",
    "remote_policy",
    "employment_type",
    "seniority",
    "work_countries",
    "eligibility_scope",
    "eligibility_source",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_interval",
    "salary_min_usd",
    "salary_max_usd",
    "salary_source",
    "salary_refusal",
    "skills",
    "source_url",
    "source_page_url",
    "source_quality",
    "description_quality",
    "posted_at",
)
_CHUNK = 500


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
        "salary_refusal": job.salary_refusal,
        "description": job.description,
        "skills": job.skills,
        "source_url": job.source_url,
        "source_page_url": job.source_page_url,
        "source_quality": job.source_quality,
        "description_quality": job.description_quality,
        "posted_at": job.posted_at,
        "content_hash": job.content_hash,
    }


async def upsert_jobs(
    session: AsyncSession,
    jobs: list[tuple[NormalisedJob, uuid.UUID]],
    now: datetime,
) -> tuple[UpsertCounts, set[uuid.UUID]]:
    """Inserts new postings and updates known ones. Returns counts and the ids seen.

    Memory: for existing jobs only (source_id, id, content_hash, status) is loaded, never
    full rows (a full row carries the description and the 384-float embedding)."""
    counts = UpsertCounts()
    seen: set[uuid.UUID] = set()
    if not jobs:
        return counts, seen
    source = jobs[0][0].source
    ids = [job.source_id for job, _ in jobs]
    existing: dict[str, tuple[uuid.UUID, str, str]] = {
        row.source_id: (row.id, row.content_hash, row.status)
        for row in await session.execute(
            select(Job.source_id, Job.id, Job.content_hash, Job.status).where(
                Job.source == source, Job.source_id.in_(ids)
            )
        )
    }
    inserts: list[dict[str, object]] = []
    changed: list[dict[str, object]] = []
    unchanged: list[dict[str, object]] = []
    for job, company_id in jobs:
        known = existing.get(job.source_id)
        fields = _fields(job, company_id)
        if known is None:
            job_id = uuid.uuid4()
            inserts.append(
                {
                    "id": job_id,
                    "source": job.source,
                    "source_id": job.source_id,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "content_changed_at": now,
                    "status": "live",
                    "missed_runs": 0,
                    **fields,
                }
            )
            # A posting listed twice in one fetch is stored once and then unchanged.
            existing[job.source_id] = (job_id, job.content_hash, "live")
            counts.new += 1
        else:
            job_id, content_hash, status = known
            if content_hash != job.content_hash:
                changed.append(
                    {
                        "id": job_id,
                        **fields,
                        "status": "updated",
                        "content_changed_at": now,
                        "last_seen_at": now,
                        "missed_runs": 0,
                    }
                )
                existing[job.source_id] = (job_id, job.content_hash, "updated")
                counts.updated += 1
            else:
                # Seen again unchanged: a returning expired job is live again; "updated"
                # lasts one run. "stale" is left for the freshness pass to decide.
                unchanged.append(
                    {
                        "id": job_id,
                        **{name: fields[name] for name in _DERIVED},
                        "status": "live" if status in ("expired", "updated") else status,
                        "last_seen_at": now,
                        "missed_runs": 0,
                    }
                )
                counts.unchanged += 1
        seen.add(job_id)
    for start in range(0, len(inserts), _CHUNK):
        await session.execute(insert(Job), inserts[start : start + _CHUNK])
    for rows in (changed, unchanged):
        for start in range(0, len(rows), _CHUNK):
            await session.execute(update(Job), rows[start : start + _CHUNK])
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


async def expire_unseen_since(session: AsyncSession, source: str, cutoff: datetime) -> int:
    """Expires the source's jobs not seen since `cutoff` (for search-result sources, where
    a job missing from one run's results has not necessarily closed)."""
    result = await session.execute(
        update(Job)
        .where(Job.source == source, Job.status != "expired", Job.last_seen_at < cutoff)
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
