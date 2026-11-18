"""Remotive public API.

GET https://remotive.com/api/remote-jobs (no auth).

Terms (https://remotive.com/api-documentation, checked 2026-11-17):
- link back to the job's Remotive URL and name Remotive as the source wherever its jobs
  are shown;
- fetch at most 4 times a day (more than 2 requests a minute are blocked);
- jobs are delayed by 24 hours;
- do not submit Remotive jobs to third-party job sites (Google Jobs, LinkedIn, ...).

The runner enforces the fetch interval (REMOTIVE_MIN_INTERVAL_HOURS); `ATTRIBUTION`
is what any screen showing a Remotive job must display, linked to the job's source_url.
"""

from typing import Any

import httpx

from app.ingest.sources.base import SourceError, get_json, parse_timestamp
from app.ingest.types import BoardResult, RawPosting

URL = "https://remotive.com/api/remote-jobs"
BOARD = "remotive"
ATTRIBUTION = "Source: Remotive"


class RemotiveAdapter:
    source = "remotive"

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        data = await get_json(http, URL)
        try:
            return BoardResult(BOARD, [_posting(job) for job in data["jobs"]])
        except (KeyError, TypeError) as exc:
            raise SourceError(f"unexpected response shape: {exc!r}") from exc


def _posting(job: dict[str, Any]) -> RawPosting:
    restriction = (job.get("candidate_required_location") or "").strip()
    return RawPosting(
        source="remotive",
        source_id=str(job["id"]),
        company_name=job["company_name"],
        title=job["title"],
        source_url=job["url"],
        description_html=job.get("description") or "",
        locations=[restriction] if restriction else [],
        workplace="remote",  # Remotive lists remote jobs only
        employment_type=job.get("job_type") or None,
        salary_text=(job.get("salary") or "").strip() or None,
        posted_at=parse_timestamp(job.get("publication_date")),
        location_restriction=restriction or None,
    )
