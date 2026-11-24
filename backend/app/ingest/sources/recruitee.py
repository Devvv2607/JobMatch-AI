"""Recruitee careers site API (no auth).

GET https://{company}.recruitee.com/api/offers/
Documented at docs.recruitee.com ("Returns a collection of published company jobs").
Checked 2026-11-24: Recruitee's terms say nothing on third-party reading of published
offers; no rate limit or pagination is documented (one request returns every offer).
"""

from typing import Any

import httpx

from app.ingest.sources.base import SourceError, get_json, parse_timestamp
from app.ingest.types import BoardResult, RawPosting, RawSalary, Workplace

URL = "https://{company}.recruitee.com/api/offers/"
_PERIOD = {"year": "year", "month": "month", "week": "week", "day": "day", "hour": "hour"}


class RecruiteeAdapter:
    source = "recruitee"

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        data = await get_json(http, URL.format(company=board))
        try:
            offers = data["offers"]
            return BoardResult(board, [p for o in offers if (p := _posting(o, company_name))])
        except (KeyError, TypeError) as exc:
            raise SourceError(f"unexpected response shape: {exc!r}") from exc


def _posting(offer: dict[str, Any], company_name: str) -> RawPosting | None:
    if (
        not offer.get("id")
        or not offer.get("title")
        or offer.get("status") not in (None, "published")
    ):
        return None
    locations = offer.get("locations") or []
    places = [
        ", ".join(str(p) for p in (loc.get("city"), loc.get("state"), loc.get("country")) if p)
        for loc in locations
    ]
    codes = sorted(
        {str(loc["country_code"]).upper() for loc in locations if loc.get("country_code")}
    )
    workplace: Workplace | None = (
        "remote"
        if offer.get("remote")
        else "hybrid"
        if offer.get("hybrid")
        else "onsite"
        if offer.get("on_site")
        else None
    )
    salary = offer.get("salary") or {}
    period = _PERIOD.get(str(salary.get("period") or "").lower())
    raw_salary = (
        RawSalary(
            _float(salary.get("min")), _float(salary.get("max")), str(salary["currency"]), period
        )
        if period and salary.get("currency") and (salary.get("min") or salary.get("max"))
        else None
    )
    return RawPosting(
        source="recruitee",
        source_id=str(offer["id"]),
        company_name=str(offer.get("company_name") or company_name),
        title=str(offer["title"]),
        source_url=str(offer.get("careers_url") or ""),
        description_html=f"{offer.get('description') or ''}\n{offer.get('requirements') or ''}",
        locations=[p for p in places if p],
        structured_countries=codes,
        structured_country_field="recruitee.locations.country_code" if codes else None,
        workplace=workplace,
        employment_type=str(offer.get("employment_type_code") or "") or None,
        salary=raw_salary,
        posted_at=parse_timestamp(offer.get("published_at") or offer.get("created_at")),
    )


def _float(value: object) -> float | None:
    try:
        return float(str(value)) if value not in (None, "") else None
    except ValueError:
        return None
