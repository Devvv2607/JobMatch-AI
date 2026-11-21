"""Adapters against responses recorded from the live APIs on 2026-11-17 (trimmed, with
descriptions shortened and contact details scrubbed). Served by httpx.MockTransport:
nothing leaves the process."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.ingest.sources.ashby import AshbyAdapter
from app.ingest.sources.base import SourceError, parse_timestamp
from app.ingest.sources.greenhouse import GreenhouseAdapter
from app.ingest.sources.lever import PAGE_SIZE, LeverAdapter
from app.ingest.sources.remotive import ATTRIBUTION, RemotiveAdapter
from app.ingest.types import RawSalary

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def serve(body: Any, seen: list[httpx.Request] | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=body)

    return client(handler)


async def test_greenhouse_maps_fields_and_requests_content() -> None:
    seen: list[httpx.Request] = []
    async with serve(fixture("greenhouse_jobs.json"), seen) as http:
        result = await GreenhouseAdapter().fetch(http, "anthropic", "Anthropic")

    assert str(seen[0].url) == (
        "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs?content=true"
    )
    assert result.board == "anthropic"
    assert len(result.postings) == 4
    mumbai = result.postings[0]
    assert mumbai.source == "greenhouse"
    assert mumbai.source_id == "5424310008"
    assert mumbai.title == "Applied AI Architect"
    assert mumbai.company_name == "Anthropic"
    assert mumbai.locations == ["Mumbai, India"]
    assert mumbai.workplace == "onsite"  # from the "Location Type" metadata field
    assert mumbai.location_restriction == "Bengaluru, Karnataka, India"
    assert mumbai.posted_at == datetime(2026, 9, 21, 7, 22, 45, tzinfo=UTC)
    assert mumbai.source_url.startswith("https://job-boards.greenhouse.io/anthropic/jobs/")
    assert "&lt;" in mumbai.description_html  # still encoded; the normaliser decodes
    assert mumbai.structured_countries == []  # Greenhouse has no structured country


async def test_lever_maps_fields_country_and_paginates() -> None:
    postings = fixture("lever_postings.json")
    full_page = [dict(postings[0], id=f"page1-{i}") for i in range(PAGE_SIZE)]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        skip = int(request.url.params["skip"])
        return httpx.Response(200, json=full_page if skip == 0 else postings)

    async with client(handler) as http:
        result = await LeverAdapter().fetch(http, "cred", "CRED")

    assert [r.url.params["skip"] for r in seen] == ["0", str(PAGE_SIZE)]
    assert all(r.url.params["mode"] == "json" for r in seen)
    assert len(result.postings) == PAGE_SIZE + 3
    posting = result.postings[PAGE_SIZE]
    assert posting.source_id == "aa98a938-af3a-45f5-851d-966b2b5bad33"
    assert posting.title == "accounts payable manager"
    assert posting.company_name == "CRED"
    assert posting.locations == ["hyderabad"]
    assert posting.structured_countries == ["IN"]
    assert posting.structured_country_field == "lever.country"
    assert posting.workplace == "onsite"
    assert posting.employment_type == "full time"
    assert posting.posted_at is not None and posting.posted_at.year == 2026


def test_lever_salary_range_is_mapped() -> None:
    from app.ingest.sources.lever import _posting

    job = dict(
        fixture("lever_postings.json")[0],
        salaryRange={
            "currency": "inr",
            "interval": "per-year-salary",
            "min": 1800000,
            "max": 2400000,
        },
    )
    assert _posting(job, "CRED").salary == RawSalary(1800000, 2400000, "INR", "year")

    job["salaryRange"] = {"currency": "USD", "interval": "one-time", "min": 1, "max": 2}
    assert _posting(job, "CRED").salary is None


async def test_ashby_maps_addresses_secondary_locations_and_compensation() -> None:
    seen: list[httpx.Request] = []
    async with serve(fixture("ashby_board.json"), seen) as http:
        result = await AshbyAdapter().fetch(http, "openai", "OpenAI")

    assert seen[0].url.params["includeCompensation"] == "true"
    delhi, us_remote, sf_hybrid, sf_london = result.postings
    assert delhi.locations == ["Delhi, India", "Mumbai, India"]
    assert delhi.structured_countries == ["IN"]
    assert delhi.structured_country_field == "ashby.address"
    assert delhi.workplace == "hybrid"
    assert delhi.employment_type == "FullTime"
    assert delhi.salary is None

    assert us_remote.workplace == "remote"
    assert us_remote.structured_countries == ["US"]
    assert us_remote.salary == RawSalary(207000, 285000, "USD", "year")  # equity skipped

    assert sf_hybrid.salary == RawSalary(207000, 285000, "USD", "year")
    assert sf_london.structured_countries == ["US", "GB"]
    assert sf_london.workplace is None  # field absent in this posting


async def test_ashby_skips_unlisted_jobs() -> None:
    body = fixture("ashby_board.json")
    body["jobs"][0]["isListed"] = False
    async with serve(body) as http:
        result = await AshbyAdapter().fetch(http, "openai", "OpenAI")
    assert len(result.postings) == 3


async def test_remotive_maps_fields_and_keeps_attribution_data() -> None:
    async with serve(fixture("remotive_jobs.json")) as http:
        result = await RemotiveAdapter().fetch(http, "ignored", "")

    assert result.board == "remotive"
    first = result.postings[0]
    assert first.company_name == "Mitre Media"
    assert first.workplace == "remote"
    assert first.location_restriction == "USA, Canada, USA timezones"
    assert first.salary_text == "$170k - $200k"
    assert first.employment_type == "full_time"
    # The Remotive job URL is kept as source_url: attribution must link to it.
    assert first.source_url.startswith("https://remotive.com/remote-jobs/")
    assert ATTRIBUTION == "Source: Remotive"
    assert result.postings[3].salary_text is None  # empty string in the feed


@pytest.mark.parametrize(
    ("adapter", "status", "message"),
    [
        (GreenhouseAdapter(), 404, "board not found"),
        (LeverAdapter(), 500, "HTTP 500"),
        (AshbyAdapter(), 429, "HTTP 429"),
        (RemotiveAdapter(), 403, "HTTP 403"),
    ],
)
async def test_http_errors_become_source_errors(adapter: Any, status: int, message: str) -> None:
    async with client(lambda _: httpx.Response(status)) as http:
        with pytest.raises(SourceError, match=message):
            await adapter.fetch(http, "board", "Company")


@pytest.mark.parametrize(
    "adapter", [GreenhouseAdapter(), LeverAdapter(), AshbyAdapter(), RemotiveAdapter()]
)
async def test_unexpected_shapes_and_non_json_become_source_errors(adapter: Any) -> None:
    async with serve({"unexpected": True}) as http:
        with pytest.raises(SourceError, match="unexpected response shape"):
            await adapter.fetch(http, "board", "Company")
    async with client(lambda _: httpx.Response(200, text="<html>maintenance</html>")) as http:
        with pytest.raises(SourceError, match="not JSON"):
            await adapter.fetch(http, "board", "Company")


async def test_network_failures_become_source_errors() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with client(refuse) as http:
        with pytest.raises(SourceError, match="request failed: ConnectError"):
            await GreenhouseAdapter().fetch(http, "board", "Company")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-05T02:20:02.702+00:00", datetime(2026, 11, 5, 2, 20, 2, 702000, tzinfo=UTC)),
        ("2026-11-14T20:33:53", datetime(2026, 11, 14, 20, 33, 53, tzinfo=UTC)),
        ("2026-11-14T20:33:53Z", datetime(2026, 11, 14, 20, 33, 53, tzinfo=UTC)),
        (1790573982021, datetime(2026, 9, 28, 5, 39, 42, 21000, tzinfo=UTC)),
        ("", None),
        (None, None),
        ("not a date", None),
    ],
)
def test_parse_timestamp(value: Any, expected: datetime | None) -> None:
    assert parse_timestamp(value) == expected
