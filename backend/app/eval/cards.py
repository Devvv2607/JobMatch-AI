"""JobCard from a stored job: what the judge and the labeller see, frozen into the pair."""

from decimal import Decimal

from app.eval.pairs import JobCard
from app.models import Company, Job

DESCRIPTION_CHARS = 4000


def eligibility_text(job: Job) -> str:
    if job.eligibility_scope == "worldwide":
        return "worldwide"
    countries = job.all_work_countries or job.work_countries
    return ", ".join(countries) if countries else "unknown"


def salary_text(job: Job) -> str | None:
    low, high = job.salary_min, job.salary_max
    if low is None and high is None:
        return None

    def num(v: Decimal | float | None) -> str:
        return f"{float(v):,.0f}" if v is not None else "?"

    span = num(low) if high is None or low == high else f"{num(low)}-{num(high)}"
    usd = ""
    if job.salary_min_usd or job.salary_max_usd:
        usd_span = "-".join(f"{v:,}" for v in (job.salary_min_usd, job.salary_max_usd) if v)
        usd = f" (about USD {usd_span} a year)"
    return f"{job.salary_currency or ''} {span} per {job.salary_interval or 'period'}{usd}".strip()


def job_card(job: Job, company: Company) -> JobCard:
    text = job.search_text or job.description
    return JobCard(
        job_id=str(job.id),
        title=job.title,
        company=company.name,
        source=job.source,
        location=job.location,
        locations=list(job.all_locations or ([job.location] if job.location else [])),
        eligibility=eligibility_text(job),
        workplace=job.remote_policy,
        employment=job.engagement_type,
        poster=job.poster_type,
        salary=salary_text(job),
        posted_at=job.posted_at.date().isoformat() if job.posted_at else None,
        url=job.source_url,
        description=text[:DESCRIPTION_CHARS],
    )
