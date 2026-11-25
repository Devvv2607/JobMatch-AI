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
from app.ingest.tags import engagement_type, poster_type
from app.ingest.text import html_to_text, normalise_key, normalise_title
from app.ingest.types import RawPosting

MAX_DESCRIPTION_CHARS = 60_000

# How directly each source publishes the posting, and whether its text is complete.
SOURCE_QUALITY = {
    "greenhouse": "ats_direct",
    "lever": "ats_direct",
    "ashby": "ats_direct",
    "smartrecruiters": "ats_direct",
    "workable": "ats_direct",
    "recruitee": "ats_direct",
    "remotive": "aggregator_full",
    "himalayas": "aggregator_full",
    "adzuna": "aggregator_snippet",  # descriptions cut at ~500 characters by the API
}


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
    engagement_type: str
    poster_type: str
    seniority: str
    work: WorkLocation
    salary: salaries.Salary | None
    salary_refusal: str | None
    description: str
    skills: list[str]
    source_url: str
    source_page_url: str | None
    source_quality: str
    description_quality: str
    posted_at: datetime | None
    content_hash: str


def normalise(posting: RawPosting) -> NormalisedJob:
    title = " ".join(html_to_text(posting.title).split())[:512]
    description = html_to_text(posting.description_html)[:MAX_DESCRIPTION_CHARS]
    location = " | ".join(posting.locations)[:1024] or (posting.location_restriction or "")[:1024]
    work = work_location(posting, description)
    salary, salary_refusal = _salary(posting, description)
    remote_policy = posting.workplace or _workplace_from_text(location)
    skills = extract_skills(f"{title}\n{description}")
    employment = employment_type(posting.employment_type, title)
    return NormalisedJob(
        source=posting.source,
        source_id=posting.source_id,
        company_name=posting.company_name.strip(),
        title=title,
        title_norm=normalise_title(title),
        location=location,
        location_norm=normalise_key(location),
        remote_policy=remote_policy,
        employment_type=employment,
        engagement_type=engagement_type(employment, title, description, posting.company_name),
        poster_type=poster_type(posting.company_name, description),
        seniority=seniority_from_title(title),
        work=work,
        salary=salary,
        salary_refusal=salary_refusal,
        description=description,
        skills=skills,
        source_url=posting.source_url,
        source_page_url=posting.page_url,
        source_quality=SOURCE_QUALITY[posting.source],
        description_quality=(
            "snippet" if SOURCE_QUALITY[posting.source] == "aggregator_snippet" else "full"
        ),
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


def _salary(posting: RawPosting, description: str) -> tuple[salaries.Salary | None, str | None]:
    """Structured ATS salary > the ATS salary text field > the description. A refusal is
    kept only when no salary was found anywhere."""
    if posting.salary is not None:
        found = salaries.from_structured(posting.salary, f"{posting.source}.salary")
        if found:
            return found, None
    field, field_refusal = salaries.text_salary(
        posting.salary_text, f"{posting.source}.salary_text", require_context=False
    )
    if field:
        return field, None
    text, text_refusal = salaries.text_salary(description, "description", require_context=True)
    if text:
        return text, None
    return None, field_refusal or text_refusal
