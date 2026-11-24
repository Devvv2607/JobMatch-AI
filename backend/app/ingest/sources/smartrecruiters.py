"""SmartRecruiters public Posting API (no auth).

GET https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset=N
lists active public postings; the description (`jobAd.sections`), apply and posting URLs
and compensation are only on the detail call
GET .../postings/{id}, so a board costs 1 + jobs/100 + jobs requests. The docs
(developers.smartrecruiters.com/docs/posting-api, checked 2026-11-24) state no rate
limit and no third-party terms; detail calls run 4 at a time per board.
"""

import asyncio
from typing import Any

import httpx

from app.ingest.sources.base import SourceError, get_json, parse_timestamp
from app.ingest.types import BoardResult, RawPosting, RawSalary, Workplace

LIST_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}"
_PERIOD = {"YEAR": "year", "MONTH": "month", "WEEK": "week", "DAY": "day", "HOUR": "hour"}
# The company's own "about us" text is the same on every posting: left out.
_SECTIONS = ("jobDescription", "qualifications", "additionalInformation")
_DETAIL_CONCURRENCY = 4
MAX_POSTINGS = 2000


class SmartRecruitersAdapter:
    source = "smartrecruiters"

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = await get_json(http, LIST_URL.format(company=board), limit=100, offset=offset)
            try:
                page = list(data["content"])
                total = int(data.get("totalFound") or 0)
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceError(f"unexpected response shape: {exc!r}") from exc
            items.extend(page)
            offset += len(page)
            if not page or offset >= total or offset >= MAX_POSTINGS:
                break
        semaphore = asyncio.Semaphore(_DETAIL_CONCURRENCY)

        async def detail(item: dict[str, Any]) -> RawPosting | None:
            async with semaphore:
                try:
                    full = await get_json(http, DETAIL_URL.format(company=board, id=item["id"]))
                except SourceError:
                    return None  # one missing posting must not fail the board
            return _posting(full, company_name)

        postings = await asyncio.gather(*(detail(item) for item in items))
        return BoardResult(board, [p for p in postings if p is not None])


def _posting(job: dict[str, Any], company_name: str) -> RawPosting | None:
    if not job.get("id") or not job.get("name"):
        return None
    location = job.get("location") or {}
    sections = (job.get("jobAd") or {}).get("sections") or {}
    description = "\n".join(
        f"<h3>{s.get('title') or ''}</h3>{s.get('text') or ''}"
        for key in _SECTIONS
        if (s := sections.get(key)) and s.get("text")
    )
    country = str(location.get("country") or "").upper()
    place = ", ".join(
        str(part) for part in (location.get("city"), location.get("region"), country) if part
    )
    workplace: Workplace | None = (
        "remote" if location.get("remote") else "hybrid" if location.get("hybrid") else None
    )
    return RawPosting(
        source="smartrecruiters",
        source_id=str(job["id"]),
        company_name=(job.get("company") or {}).get("name") or company_name,
        title=str(job["name"]),
        source_url=str(job.get("postingUrl") or job.get("applyUrl") or ""),
        description_html=description,
        locations=[place] if place else [],
        structured_countries=[country] if len(country) == 2 else [],
        structured_country_field="smartrecruiters.location.country" if len(country) == 2 else None,
        workplace=workplace,
        employment_type=(job.get("typeOfEmployment") or {}).get("label"),
        salary=_salary(job.get("compensation") or {}),
        posted_at=parse_timestamp(job.get("releasedDate")),
    )


def _salary(comp: dict[str, Any]) -> RawSalary | None:
    period = _PERIOD.get(str(comp.get("period") or "").upper())
    if not comp.get("currency") or period is None:
        return None
    low, high = comp.get("min"), comp.get("max")
    if low is None and high is None:
        return None
    return RawSalary(
        float(low) if low is not None else None,
        float(high) if high is not None else None,
        str(comp["currency"]),
        period,
    )
