from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from app.ingest.types import BoardResult

USER_AGENT = "jobmatch-ingest/0.1 (job-board aggregation; respects published rate limits)"


class SourceError(Exception):
    """A board could not be fetched or parsed. Recorded per board; never fatal to a run."""


class Adapter(Protocol):
    source: str

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        """Fetch every published posting on one board."""
        ...


async def get_json(http: httpx.AsyncClient, url: str, **params: Any) -> Any:
    try:
        response = await http.get(url, params=params or None)
    except httpx.HTTPError as exc:
        raise SourceError(f"request failed: {type(exc).__name__}") from exc
    if response.status_code == 404:
        raise SourceError("board not found (HTTP 404)")
    if response.status_code != 200:
        raise SourceError(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise SourceError("response was not JSON") from exc


def parse_timestamp(value: Any) -> datetime | None:
    """ISO-8601 strings and epoch milliseconds; anything else is None."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
