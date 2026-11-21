"""Greenhouse public Job Board API.

GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true (no auth).
`content` is HTML with entities encoded once more; the normaliser decodes it.
"""

import re
from typing import Any

import httpx

from app.ingest.sources.base import SourceError, get_json, parse_timestamp
from app.ingest.types import BoardResult, RawPosting, Workplace

URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

# Companies configure their own metadata fields; these are the names used for workplace.
_WORKPLACE_FIELD = re.compile(r"location type|workplace|remote", re.I)
_WORKPLACE_VALUES: dict[str, Workplace] = {
    "remote": "remote",
    "fully remote": "remote",
    "hybrid": "hybrid",
    "on-site": "onsite",
    "onsite": "onsite",
    "in office": "onsite",
    "in-office": "onsite",
}


class GreenhouseAdapter:
    source = "greenhouse"

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        data = await get_json(http, URL.format(token=board), content="true")
        try:
            jobs = data["jobs"]
            return BoardResult(board, [_posting(job, company_name) for job in jobs])
        except (KeyError, TypeError) as exc:
            raise SourceError(f"unexpected response shape: {exc!r}") from exc


def _posting(job: dict[str, Any], company_name: str) -> RawPosting:
    offices = job.get("offices") or []
    office_locations = [o.get("location") or o.get("name") or "" for o in offices]
    location_name = (job.get("location") or {}).get("name") or ""
    return RawPosting(
        source="greenhouse",
        source_id=str(job["id"]),
        company_name=job.get("company_name") or company_name,
        title=job["title"],
        source_url=job["absolute_url"],
        description_html=job.get("content") or "",
        locations=[loc for loc in [location_name] if loc],
        workplace=_workplace(job.get("metadata") or []),
        posted_at=parse_timestamp(job.get("first_published") or job.get("updated_at")),
        # Office records are configured places, but a remote role is often attached to
        # the head office, so they are only a hint; the location rules decide.
        location_restriction=" | ".join(loc for loc in office_locations if loc) or None,
    )


def _workplace(metadata: list[dict[str, Any]]) -> Workplace | None:
    for field in metadata:
        if not _WORKPLACE_FIELD.search(str(field.get("name") or "")):
            continue
        value = field.get("value")
        values = value if isinstance(value, list) else [value]
        for item in values:
            mapped = _WORKPLACE_VALUES.get(str(item or "").strip().lower())
            if mapped:
                return mapped
    return None
