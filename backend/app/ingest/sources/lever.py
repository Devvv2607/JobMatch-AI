"""Lever postings API.

GET https://api.lever.co/v0/postings/{site}?mode=json (no auth). Returns a JSON array of
published postings. `country` is ISO 3166-1 alpha-2 and `workplaceType` is one of
unspecified / on-site / remote / hybrid.
"""

from typing import Any

import httpx

from app.ingest.sources.base import SourceError, get_json, parse_timestamp
from app.ingest.types import BoardResult, RawPosting, RawSalary, Workplace

URL = "https://api.lever.co/v0/postings/{site}"
PAGE_SIZE = 100

# The docs say "on-site"; live responses (2026-11-17) send "onsite". Both are accepted.
_WORKPLACE: dict[str, Workplace] = {
    "remote": "remote",
    "hybrid": "hybrid",
    "on-site": "onsite",
    "onsite": "onsite",
}
_INTERVALS = {
    "per-year-salary": "year",
    "per-month-salary": "month",
    "per-week-salary": "week",
    "per-day-wage": "day",
    "per-hour-wage": "hour",
}


class LeverAdapter:
    source = "lever"

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        postings: list[RawPosting] = []
        skip = 0
        while True:
            page = await get_json(
                http, URL.format(site=board), mode="json", skip=skip, limit=PAGE_SIZE
            )
            if not isinstance(page, list):
                raise SourceError("unexpected response shape: expected a list")
            try:
                postings.extend(_posting(job, company_name) for job in page)
            except (KeyError, TypeError) as exc:
                raise SourceError(f"unexpected response shape: {exc!r}") from exc
            if len(page) < PAGE_SIZE:
                return BoardResult(board, postings)
            skip += PAGE_SIZE


def _posting(job: dict[str, Any], company_name: str) -> RawPosting:
    categories = job.get("categories") or {}
    locations = [categories.get("location") or "", *(categories.get("allLocations") or [])]
    country = (job.get("country") or "").strip().upper()
    description = "\n".join(
        part
        for part in [
            job.get("description") or "",
            *(
                f"<h3>{item.get('text') or ''}</h3><ul>{item.get('content') or ''}</ul>"
                for item in job.get("lists") or []
            ),
            job.get("additional") or "",
        ]
        if part
    )
    return RawPosting(
        source="lever",
        source_id=str(job["id"]),
        company_name=company_name,
        title=job["text"],
        source_url=job["hostedUrl"],
        description_html=description,
        locations=list(dict.fromkeys(loc for loc in locations if loc)),
        structured_countries=[country] if len(country) == 2 else [],
        structured_country_field="lever.country" if len(country) == 2 else None,
        workplace=_WORKPLACE.get(str(job.get("workplaceType") or "").lower()),
        employment_type=categories.get("commitment"),
        salary=_salary(job.get("salaryRange")),
        salary_text=job.get("salaryDescriptionPlain"),
        posted_at=parse_timestamp(job.get("createdAt")),
    )


def _salary(raw: Any) -> RawSalary | None:
    if not isinstance(raw, dict) or not raw.get("currency"):
        return None
    interval = _INTERVALS.get(str(raw.get("interval") or ""))
    if interval is None or (raw.get("min") is None and raw.get("max") is None):
        return None
    return RawSalary(
        min=raw.get("min"),
        max=raw.get("max"),
        currency=str(raw["currency"]).upper(),
        interval=interval,
    )
