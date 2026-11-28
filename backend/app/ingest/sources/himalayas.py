"""Himalayas remote jobs API (no key).

GET https://himalayas.app/jobs/api/search?country=IN&page=N (country filter includes
worldwide-friendly jobs unless exclude_worldwide is set). Pages hold up to 20 jobs and
can be short before the end, so paging stops only on an empty page.

Terms (https://himalayas.app/api and /terms, checked 2026-11-24):
- jobs may be shown on sites we operate, without asking first;
- every Apply button uses `applicationLink`, unchanged (stored as source_url);
- show a visible link to the job on Himalayas or to himalayas.app as the source
  (`guid`, stored as source_page_url; `ATTRIBUTION`);
- never pass the jobs on to other job boards, aggregators, Google Jobs or LinkedIn Jobs,
  including through feeds or JobPosting structured data;
- remove jobs once they expire (expired ones are skipped; missing ones expire after two
  successful runs, like every source);
- unkeyed requests have lower, unpublished limits: one request per second here, backing
  off on 429; responses are cached by Himalayas for an hour or more, so the runner
  fetches at most every HIMALAYAS_MIN_INTERVAL_HOURS.

Eligibility: `locationRestrictions` (country names) are the countries the job can be
done from; with none but `timezoneRestrictions`, the countries whose UTC offsets fit the
listed offsets (data/utc_offsets.yaml); with neither, or with timezones admitting every
country, worldwide ("Remote, worldwide").
"""

import asyncio
import logging
import math
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.ingest.countries import country_code
from app.ingest.sources.base import SourceError
from app.ingest.types import BoardResult, RawPosting, RawSalary

logger = logging.getLogger(__name__)

URL = "https://himalayas.app/jobs/api/search"
BOARD = "himalayas"
ATTRIBUTION = "Source: Himalayas"
WORLDWIDE = "Remote, worldwide"  # the location shown for jobs open everywhere
_PERIOD = {"annual": "year", "monthly": "month", "weekly": "week", "hourly": "hour"}
_OFFSETS = Path(__file__).resolve().parents[1] / "data" / "utc_offsets.yaml"


@cache
def utc_offsets() -> dict[str, tuple[float, float]]:
    raw = yaml.safe_load(_OFFSETS.read_text(encoding="utf-8"))
    return {code: (float(lo), float(hi)) for code, (lo, hi) in raw.items()}


def countries_in_timezones(offsets: list[float]) -> list[str]:
    """Countries whose whole offset range is covered by the listed offsets, each widened by
    one hour (for daylight saving). Lists can have gaps (Americas and Asia, not Europe), so
    every whole hour of a country's range must be near a listed offset, not just lie
    between the smallest and largest."""

    def covered(x: float) -> bool:
        return any(abs(x - t) <= 1 for t in offsets)

    def fits(lo: float, hi: float) -> bool:
        points = [lo, hi, *range(math.ceil(lo), math.floor(hi) + 1)]
        return all(covered(x) for x in points)

    return sorted(c for c, (lo, hi) in utc_offsets().items() if fits(lo, hi))


def covers_every_country(offsets: list[float]) -> bool:
    """A timezone list that admits every country we map is no restriction at all."""
    return len(countries_in_timezones(offsets)) == len(utc_offsets())


class HimalayasAdapter:
    source = "himalayas"

    def __init__(
        self, country: str = "IN", max_pages: int = 400, delay_seconds: float = 1.0
    ) -> None:
        self.country = country
        self.max_pages = max_pages
        self.delay = delay_seconds

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        postings: list[RawPosting] = []
        seen: set[str] = set()
        now = datetime.now(UTC)
        for page in range(1, self.max_pages + 1):
            jobs = await self._page(http, page)
            if not jobs:
                break
            for job in jobs:
                posting = _posting(job, now)
                if posting is not None and posting.source_id not in seen:
                    seen.add(posting.source_id)
                    postings.append(posting)
            await asyncio.sleep(self.delay)
        else:
            logger.warning(
                "himalayas: stopped at the page cap; later pages not fetched",
                extra={"max_pages": self.max_pages, "jobs": len(postings)},
            )
        return BoardResult(BOARD, postings)

    async def _page(self, http: httpx.AsyncClient, page: int) -> list[dict[str, Any]]:
        for attempt in range(4):
            try:
                response = await http.get(URL, params={"country": self.country, "page": page})
            except httpx.HTTPError as exc:
                raise SourceError(f"page {page}: {type(exc).__name__}") from exc
            if response.status_code == 429:
                wait = float(response.headers.get("retry-after") or 10 * (attempt + 1))
                await asyncio.sleep(min(wait, 60))
                continue
            if response.status_code != 200:
                raise SourceError(f"page {page}: HTTP {response.status_code}")
            try:
                jobs = response.json()["jobs"]
            except (ValueError, KeyError, TypeError) as exc:
                raise SourceError(f"page {page}: unexpected response") from exc
            return list(jobs or [])
        raise SourceError(f"page {page}: still rate-limited after 4 attempts")


def _posting(job: dict[str, Any], now: datetime) -> RawPosting | None:
    expiry = job.get("expiryDate")
    if isinstance(expiry, int | float) and datetime.fromtimestamp(expiry, UTC) < now:
        return None  # "Remove jobs once they expire."
    guid = str(job.get("guid") or "")
    apply = str(job.get("applicationLink") or guid)
    if not guid or not job.get("title"):
        return None
    countries = sorted(
        {c for name in job.get("locationRestrictions") or [] if (c := country_code(str(name)))}
    )
    timezones = [float(t) for t in job.get("timezoneRestrictions") or [] if _is_number(t)]
    field = "himalayas.locationRestrictions"
    if not countries and timezones and covers_every_country(timezones):
        timezones = []  # every timezone: open worldwide, not a 77-country list
    if not countries and timezones:
        countries = countries_in_timezones(timezones)
        field = "himalayas.timezoneRestrictions"
    pub = job.get("pubDate")
    return RawPosting(
        source="himalayas",
        source_id=guid[-128:],
        company_name=str(job.get("companyName") or "").strip() or "Unknown",
        title=str(job["title"]),
        source_url=apply,
        page_url=guid,
        description_html=str(job.get("description") or job.get("excerpt") or ""),
        locations=[],
        structured_countries=countries,
        structured_country_field=field if countries else None,
        workplace="remote",  # Himalayas lists remote jobs only
        employment_type=str(job.get("employmentType") or "") or None,
        salary=_salary(job),
        posted_at=datetime.fromtimestamp(pub, UTC) if isinstance(pub, int | float) else None,
        # No restriction of either kind (or every timezone): open worldwide.
        location_restriction=None if countries or timezones else WORLDWIDE,
    )


def _salary(job: dict[str, Any]) -> RawSalary | None:
    low, high = job.get("minSalary"), job.get("maxSalary")
    currency = job.get("currency")
    if not currency or (low is None and high is None):
        return None
    period = _PERIOD.get(str(job.get("salaryPeriod") or "annual").lower())
    if period is None:  # "fortnightly" and anything new: not converted
        return None
    return RawSalary(
        float(low) if low is not None else None,
        float(high) if high is not None else None,
        str(currency),
        period,
    )


def _is_number(value: object) -> bool:
    try:
        float(str(value))
    except ValueError:
        return False
    return True
