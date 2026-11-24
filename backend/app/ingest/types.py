from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Workplace = Literal["remote", "hybrid", "onsite"]


@dataclass(frozen=True)
class RawSalary:
    min: float | None
    max: float | None
    currency: str
    interval: str  # "year" | "month" | "week" | "day" | "hour"


@dataclass(frozen=True)
class RawPosting:
    """One posting as an adapter maps it from its source, before normalisation.

    Adapters only translate fields; they do not interpret locations, skills or seniority.
    Every text field may contain untrusted HTML.
    """

    source: str
    source_id: str
    company_name: str
    title: str
    source_url: str
    description_html: str
    # Human-readable location strings, as the source lists them (one per location).
    locations: list[str] = field(default_factory=list)
    # ISO 3166-1 alpha-2 codes from structured source fields (Lever `country`,
    # Ashby postal addresses). Empty when the source has no structured country.
    structured_countries: list[str] = field(default_factory=list)
    # Which structured field the countries came from, e.g. "lever.country".
    structured_country_field: str | None = None
    workplace: Workplace | None = None
    employment_type: str | None = None
    salary: RawSalary | None = None
    salary_text: str | None = None
    posted_at: datetime | None = None
    # Remotive's candidate_required_location, Greenhouse office names, and similar.
    location_restriction: str | None = None
    # The job's page on an aggregator (Himalayas), when source_url is the apply link.
    page_url: str | None = None


@dataclass
class BoardResult:
    """Everything fetched from one board (or one source-wide feed)."""

    board: str
    postings: list[RawPosting]
