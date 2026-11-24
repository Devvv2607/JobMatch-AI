"""Adzuna job search API (free key: ADZUNA_APP_ID / ADZUNA_APP_KEY).

GET https://api.adzuna.com/v1/api/jobs/in/search/{page}?what=...&results_per_page=50
(India; checked live 2026-11-24: "software engineer" matched 26,597 jobs).

Terms (https://developer.adzuna.com/docs/terms_of_service, checked 2026-11-24):
- permitted uses include "Publishing Adzuna ad listings"; each displayed advert must be
  labelled "Adzuna", hyperlinked to the local Adzuna domain (`ATTRIBUTION`);
- the job link is Adzuna's `redirect_url` (stored as source_url);
- commercial organisations get a 14-day trial, and "any use in a product or service that
  generates revenue or leads" needs a licence. JobMatch is a non-commercial project;
  revisit this before any commercial use;
- the free tier is "intended for evaluating the API". The owner's account is on the
  free testing tier: 25 calls a minute, and (the standard testing limits, assumed until
  a response says otherwise) 250 a day, 1,000 a week and 2,500 a month. All four are
  settings (ADZUNA_*_CALL_LIMIT). Every call is counted in Redis per UTC minute, day,
  ISO week and calendar month (`Usage`). At ADZUNA_QUOTA_STOP_SHARE (80%) of the
  minute limit the adapter waits for the next minute; at 80% of the day, week or month
  it stops. HTTP 429 backs off (Retry-After, else 30 s, 60 s, 90 s) and gives up after
  three tries. Any rate-limit headers in a response are logged once a run, so a limit
  Adzuna states can replace the assumed ones.

Descriptions are snippets (~500 characters): description_quality = "snippet".
Predicted salaries (`salary_is_predicted` = 1) are Adzuna's estimate, not the
employer's, and are ignored.

Adzuna returns search results, not a complete feed, so a job missing from one run's
results has not necessarily closed: Adzuna jobs expire by age instead (runner).
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from redis.asyncio import Redis

from app.ingest.sources.base import SourceError, parse_timestamp
from app.ingest.types import BoardResult, RawPosting, RawSalary

logger = logging.getLogger(__name__)

URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
BOARD = "adzuna"
ATTRIBUTION = "Adzuna"  # linked to https://www.adzuna.in
USAGE_KEY = "adzuna:calls:{window}:{period}"
_TTL_SECONDS = {"minute": 120, "day": 2 * 86400, "week": 9 * 86400, "month": 40 * 86400}


class QuotaReachedError(SourceError):
    pass


def periods(now: datetime) -> dict[str, str]:
    """The UTC period each window's counter is keyed by."""
    year, week, _ = now.isocalendar()
    return {
        "minute": now.strftime("%Y%m%dT%H%M"),
        "day": now.strftime("%Y%m%d"),
        "week": f"{year}W{week:02d}",
        "month": now.strftime("%Y%m"),
    }


class Usage:
    """Adzuna calls counted per window in Redis (shared by every process)."""

    def __init__(self, redis: Redis, limits: dict[str, int], stop_share: float) -> None:
        self.redis = redis
        self.limits = limits
        self.stop_share = stop_share

    def keys(self, now: datetime) -> dict[str, str]:
        return {
            window: USAGE_KEY.format(window=window, period=period)
            for window, period in periods(now).items()
        }

    async def counts(self, now: datetime) -> dict[str, int]:
        keys = self.keys(now)
        values = await self.redis.mget(list(keys.values()))
        return {window: int(v or 0) for window, v in zip(keys, values, strict=True)}

    def over(self, counts: dict[str, int]) -> list[str]:
        """Windows at or past their stop share, shortest first."""
        return [
            window
            for window, limit in self.limits.items()
            if counts.get(window, 0) >= limit * self.stop_share
        ]

    async def record(self, now: datetime) -> None:
        async with self.redis.pipeline(transaction=True) as pipe:
            for window, key in self.keys(now).items():
                pipe.incr(key)
                pipe.expire(key, _TTL_SECONDS[window])
            await pipe.execute()


class AdzunaAdapter:
    source = "adzuna"

    def __init__(
        self,
        app_id: str,
        app_key: str,
        redis: Redis,
        *,
        queries: list[str],
        pages_per_query: int,
        limits: dict[str, int],
        stop_share: float,
        country: str = "in",
        delay_seconds: float = 2.5,
        backoff_seconds: float = 30.0,
    ) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.usage = Usage(redis, limits, stop_share)
        self.queries = queries
        self.pages = pages_per_query
        self.country = country
        self.delay = delay_seconds
        self.backoff = backoff_seconds
        self._logged_headers = False

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        if not (self.app_id and self.app_key):
            raise SourceError("ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
        postings: dict[str, RawPosting] = {}
        stopped = None
        for query in self.queries:
            for page in range(1, self.pages + 1):
                try:
                    results = await self._call(http, query, page)
                except QuotaReachedError as exc:
                    stopped = str(exc)
                    break
                for item in results:
                    posting = _posting(item)
                    if posting is not None:
                        postings.setdefault(posting.source_id, posting)
                if len(results) < 50:
                    break
                await asyncio.sleep(self.delay)
            if stopped:
                break
        if stopped and not postings:
            raise SourceError(stopped)
        if stopped:
            logger.warning("adzuna: stopped early", extra={"reason": stopped})
        return BoardResult(BOARD, list(postings.values()))

    async def _wait_for_room(self) -> None:
        """Waits out the minute window; raises QuotaReachedError for day/week/month."""
        while True:
            now = datetime.now(UTC)
            counts = await self.usage.counts(now)
            over = self.usage.over(counts)
            stopping = [w for w in over if w != "minute"]
            if stopping:
                window = stopping[-1]  # the longest window reached
                raise QuotaReachedError(
                    f"{window} Adzuna calls at {counts[window]} of {self.usage.limits[window]} "
                    f"(stops at {self.usage.stop_share:.0%})"
                )
            if not over:
                return
            await asyncio.sleep(60.5 - now.second - now.microsecond / 1e6)

    async def _call(self, http: httpx.AsyncClient, query: str, page: int) -> list[dict[str, Any]]:
        for attempt in range(1, 4):
            await self._wait_for_room()
            await self.usage.record(datetime.now(UTC))
            response = await self._get(http, query, page)
            if response.status_code != 429:
                return self._results(response, query, page)
            wait = response.headers.get("retry-after")
            seconds = float(wait) if wait and wait.isdigit() else self.backoff * attempt
            logger.warning("adzuna: HTTP 429, backing off", extra={"seconds": seconds})
            await asyncio.sleep(min(seconds, 300))
        raise SourceError(f"{query!r} page {page}: still rate-limited (HTTP 429) after 3 tries")

    async def _get(self, http: httpx.AsyncClient, query: str, page: int) -> httpx.Response:
        params: dict[str, str | int] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": 50,
            "what": query,
            "content-type": "application/json",
        }
        try:
            response = await http.get(URL.format(country=self.country, page=page), params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"{query!r} page {page}: {type(exc).__name__}") from exc
        limits = {k: v for k, v in response.headers.items() if "ratelimit" in k.lower()}
        if limits and not self._logged_headers:
            logger.info("adzuna: rate-limit headers", extra={"headers": limits})
            self._logged_headers = True
        return response

    def _results(self, response: httpx.Response, query: str, page: int) -> list[dict[str, Any]]:
        if response.status_code != 200:
            # The key is in the URL: never put the URL or body in the error.
            raise SourceError(f"{query!r} page {page}: HTTP {response.status_code}")
        try:
            return list(response.json().get("results") or [])
        except ValueError as exc:
            raise SourceError(f"{query!r} page {page}: response was not JSON") from exc


def _posting(item: dict[str, Any]) -> RawPosting | None:
    if not item.get("id") or not item.get("title") or not item.get("redirect_url"):
        return None
    location = item.get("location") or {}
    area = [str(a) for a in location.get("area") or []]
    company = (item.get("company") or {}).get("display_name") or "Unknown"
    return RawPosting(
        source="adzuna",
        source_id=str(item["id"]),
        company_name=str(company),
        title=str(item["title"]),
        source_url=str(item["redirect_url"]),
        description_html=str(item.get("description") or ""),
        locations=[str(location.get("display_name") or "")] if location.get("display_name") else [],
        # area[0] is the country ("India" for this endpoint).
        structured_countries=["IN"] if area[:1] == ["India"] else [],
        structured_country_field="adzuna.location.area" if area[:1] == ["India"] else None,
        employment_type=str(item.get("contract_time") or "") or None,
        salary=_salary(item),
        posted_at=parse_timestamp(item.get("created")),
    )


def _salary(item: dict[str, Any]) -> RawSalary | None:
    if str(item.get("salary_is_predicted") or "0") == "1":
        return None  # Adzuna's estimate, not the employer's figure
    low, high = item.get("salary_min"), item.get("salary_max")
    if low is None and high is None:
        return None
    return RawSalary(
        float(low) if low is not None else None,
        float(high) if high is not None else None,
        "INR",
        "year",
    )
