"""Workable public jobs endpoint (no auth).

GET https://www.workable.com/api/accounts/{subdomain}?details=true
Documented under "Public Endpoints" at workable.readme.io ("Returns a collection of the
public jobs for an account"; `details=true` adds the description). Checked 2026-11-24:
Workable's terms (workable.com/terms) bind its customers and say nothing on third-party
reading of these public jobs; no rate limit is stated.
"""

from typing import Any

import httpx

from app.ingest.countries import country_code
from app.ingest.sources.base import SourceError, get_json, parse_timestamp
from app.ingest.types import BoardResult, RawPosting, Workplace

URL = "https://www.workable.com/api/accounts/{subdomain}"
_WORKPLACE: dict[str, Workplace] = {"remote": "remote", "hybrid": "hybrid", "on_site": "onsite"}


class WorkableAdapter:
    source = "workable"

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        data = await get_json(http, URL.format(subdomain=board), details="true")
        try:
            jobs = data["jobs"]
            name = data.get("name") or company_name
            return BoardResult(board, [p for job in jobs if (p := _posting(job, name))])
        except (KeyError, TypeError) as exc:
            raise SourceError(f"unexpected response shape: {exc!r}") from exc


def _posting(job: dict[str, Any], company_name: str) -> RawPosting | None:
    if not job.get("shortcode") or not job.get("title"):
        return None
    place = ", ".join(str(p) for p in (job.get("city"), job.get("state"), job.get("country")) if p)
    code = country_code(str(job.get("country") or ""))
    workplace = _WORKPLACE.get(str(job.get("workplace_type") or "").lower())
    if workplace is None and job.get("telecommuting"):
        workplace = "remote"
    return RawPosting(
        source="workable",
        source_id=str(job["shortcode"]),
        company_name=company_name,
        title=str(job["title"]),
        source_url=str(job.get("url") or job.get("application_url") or ""),
        description_html=str(job.get("description") or ""),
        locations=[place] if place else [],
        structured_countries=[code] if code else [],
        structured_country_field="workable.country" if code else None,
        workplace=workplace,
        employment_type=str(job.get("employment_type") or "") or None,
        posted_at=parse_timestamp(job.get("published_on") or job.get("created_at")),
    )
