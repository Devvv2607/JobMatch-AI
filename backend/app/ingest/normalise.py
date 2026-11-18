"""RawPosting -> the fields of a Job row."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime

from app.ingest import salary as salaries
from app.ingest.eligibility import WorkLocation, work_location
from app.ingest.seniority import employment_type, seniority_from_title
from app.ingest.skills import extract_skills
from app.ingest.text import html_to_text, normalise_key, normalise_title
from app.ingest.types import RawPosting

MAX_DESCRIPTION_CHARS = 60_000


@dataclass(frozen=True)
class NormalisedJob:
    source: str
    source_id: str
    company_name: str
    title: str
    title_norm: str
    location: str
    location_norm: str
    remote_policy: str
    employment_type: str
    seniority: str
    work: WorkLocation
    salary: salaries.Salary | None
    description: str
    skills: list[str]
    source_url: str
    posted_at: datetime | None
    content_hash: str


def normalise(posting: RawPosting) -> NormalisedJob:
    title = " ".join(html_to_text(posting.title).split())[:512]
    description = html_to_text(posting.description_html)[:MAX_DESCRIPTION_CHARS]
    location = " | ".join(posting.locations)[:1024] or (posting.location_restriction or "")[:1024]
    work = work_location(posting, description)
    salary = _salary(posting, description)
    remote_policy = posting.workplace or _workplace_from_text(location)
    skills = extract_skills(f"{title}\n{description}")
    return NormalisedJob(
        source=posting.source,
        source_id=posting.source_id,
        company_name=posting.company_name.strip(),
        title=title,
        title_norm=normalise_title(title),
        location=location,
        location_norm=normalise_key(location),
        remote_policy=remote_policy,
        employment_type=employment_type(posting.employment_type, title),
        seniority=seniority_from_title(title),
        work=work,
        salary=salary,
        description=description,
        skills=skills,
        source_url=posting.source_url,
        posted_at=posting.posted_at,
        content_hash=content_hash(title, description, location, salary),
    )


def content_hash(
    title: str, description: str, location: str, salary: salaries.Salary | None
) -> str:
    """Changes when anything a candidate would care about changes. Includes location, so
    two postings with the same text in different countries never share a hash."""
    material = json.dumps(
        [
            normalise_title(title),
            " ".join(description.split()),
            normalise_key(location),
            [salary.min, salary.max, salary.currency, salary.interval] if salary else None,
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()


_REMOTE_WORDS = re.compile(r"\bremote\b", re.I)
_HYBRID_WORDS = re.compile(r"\bhybrid\b", re.I)


def _workplace_from_text(location: str) -> str:
    """Only when the source has no workplace field. A bare city is not evidence of an
    on-site role, so it stays unknown (an on-site dealbreaker keeps and flags it)."""
    if _HYBRID_WORDS.search(location):
        return "hybrid"
    if _REMOTE_WORDS.search(location):
        return "remote"
    return "unknown"


def _salary(posting: RawPosting, description: str) -> salaries.Salary | None:
    if posting.salary is not None:
        found = salaries.from_structured(posting.salary, f"{posting.source}.salary")
        if found:
            return found
    return salaries.from_text(posting.salary_text, f"{posting.source}.salary_text") or (
        salaries.from_text(description, "description")
    )
