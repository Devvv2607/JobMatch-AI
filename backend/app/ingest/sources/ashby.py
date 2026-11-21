"""Ashby public job posting API.

GET https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true
(no auth). Countries arrive as names in address.postalAddress.addressCountry.
"""

from typing import Any

import httpx

from app.ingest.countries import country_code
from app.ingest.sources.base import SourceError, get_json, parse_timestamp
from app.ingest.types import BoardResult, RawPosting, RawSalary, Workplace

URL = "https://api.ashbyhq.com/posting-api/job-board/{name}"

_WORKPLACE: dict[str, Workplace] = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}
_INTERVALS = {
    "1 YEAR": "year",
    "1 MONTH": "month",
    "1 WEEK": "week",
    "1 DAY": "day",
    "1 HOUR": "hour",
}


class AshbyAdapter:
    source = "ashby"

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        data = await get_json(http, URL.format(name=board), includeCompensation="true")
        try:
            jobs = [job for job in data["jobs"] if job.get("isListed", True)]
            return BoardResult(board, [_posting(job, company_name) for job in jobs])
        except (KeyError, TypeError) as exc:
            raise SourceError(f"unexpected response shape: {exc!r}") from exc


def _posting(job: dict[str, Any], company_name: str) -> RawPosting:
    secondary = job.get("secondaryLocations") or []
    locations = [job.get("location") or "", *(s.get("location") or "" for s in secondary)]
    addresses = [job.get("address"), *(s.get("address") for s in secondary)]
    countries = [
        code
        for address in addresses
        if (code := country_code(_address_country(address))) is not None
    ]
    return RawPosting(
        source="ashby",
        source_id=str(job["id"]),
        company_name=company_name,
        title=job["title"],
        source_url=job["jobUrl"],
        description_html=job.get("descriptionHtml") or "",
        locations=list(dict.fromkeys(loc for loc in locations if loc)),
        structured_countries=list(dict.fromkeys(countries)),
        structured_country_field="ashby.address" if countries else None,
        workplace=_WORKPLACE.get(str(job.get("workplaceType") or "").lower()),
        employment_type=job.get("employmentType"),
        salary=_salary(job.get("compensation")),
        posted_at=parse_timestamp(job.get("publishedAt")),
    )


def _address_country(address: Any) -> str:
    if not isinstance(address, dict):
        return ""
    postal = address.get("postalAddress") or address
    return str(postal.get("addressCountry") or "")


def _salary(compensation: Any) -> RawSalary | None:
    """The first salary component of the first tier that has one."""
    if not isinstance(compensation, dict):
        return None
    for tier in compensation.get("compensationTiers") or []:
        for component in tier.get("components") or []:
            if component.get("compensationType") != "Salary":
                continue
            interval = _INTERVALS.get(str(component.get("interval") or ""))
            low, high = component.get("minValue"), component.get("maxValue")
            if interval and component.get("currencyCode") and (low or high):
                return RawSalary(
                    min=low, max=high, currency=component["currencyCode"], interval=interval
                )
    return None
