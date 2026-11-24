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
- the free tier is "intended for evaluating the API"; its limits are shown only in the
  account. ADZUNA_MONTHLY_CALL_QUOTA is therefore a setting (default 2,500: an
  assumption, not a published number). Every call is counted in Redis per calendar
  month, and the adapter stops at ADZUNA_QUOTA_STOP_SHARE (80%) of it.

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
USAGE_KEY = "adzuna:calls:{month}"


class QuotaReachedError(SourceError):
    pass


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
        monthly_quota: int,
        stop_share: float,
        country: str = "in",
        delay_seconds: float = 2.5,
    ) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.redis = redis
        self.queries = queries
        self.pages = pages_per_query
        self.monthly_quota = monthly_quota
        self.stop_share = stop_share
        self.country = country
        self.delay = delay_seconds

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

    async def _call(self, http: httpx.AsyncClient, query: str, page: int) -> list[dict[str, Any]]:
        key = USAGE_KEY.format(month=datetime.now(UTC).strftime("%Y%m"))
        used = int(await self.redis.get(key) or 0)
        if used >= self.monthly_quota * self.stop_share:
            raise QuotaReachedError(
                f"monthly Adzuna calls at {used} of {self.monthly_quota} "
                f"(stops at {self.stop_share:.0%})"
            )
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, 40 * 86400)
            await pipe.execute()
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
