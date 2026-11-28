"""The Phase 2b adapters against mocked HTTP (httpx.MockTransport). Fixtures are synthetic,
shaped like each source's documented response; no request leaves the process."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.core.redis import redis
from app.ingest.companies import match_key
from app.ingest.normalise import normalise
from app.ingest.sources import adzuna as adzuna_module
from app.ingest.sources.adzuna import AdzunaAdapter, Usage, periods
from app.ingest.sources.base import SourceError
from app.ingest.sources.himalayas import (
    WORLDWIDE,
    HimalayasAdapter,
    countries_in_timezones,
    utc_offsets,
)
from app.ingest.sources.recruitee import RecruiteeAdapter
from app.ingest.sources.smartrecruiters import SmartRecruitersAdapter
from app.ingest.sources.workable import WorkableAdapter

Handler = Callable[[httpx.Request], httpx.Response]


def client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


NOW = datetime.now(UTC)


def himalayas_job(i: int, **overrides: Any) -> dict[str, Any]:
    job: dict[str, Any] = {
        "title": f"Backend Engineer {i}",
        "companyName": "Acme",
        "description": "<p>Python and PostgreSQL. Salary: ₹30L – ₹40L per annum.</p>",
        "excerpt": "Python",
        "applicationLink": f"https://acme.example/apply/{i}",
        "guid": f"https://himalayas.app/companies/acme/jobs/backend-{i}",
        "locationRestrictions": [],
        "timezoneRestrictions": [],
        "employmentType": "Full Time",
        "minSalary": None,
        "maxSalary": None,
        "currency": None,
        "salaryPeriod": "annual",
        "pubDate": int((NOW - timedelta(days=1)).timestamp()),
        "expiryDate": int((NOW + timedelta(days=30)).timestamp()),
    }
    job.update(overrides)
    return job


async def test_himalayas_pages_until_an_empty_page_and_maps_restrictions() -> None:
    pages = {
        1: [
            himalayas_job(1),  # no restriction: worldwide
            himalayas_job(2, locationRestrictions=["India", "Singapore"]),
            himalayas_job(3, timezoneRestrictions=[5, 6]),  # IN (+5.5) fits, US does not
            himalayas_job(4, expiryDate=int((NOW - timedelta(days=1)).timestamp())),  # expired
        ],
        2: [himalayas_job(5, minSalary=100000, maxSalary=120000, currency="USD")],  # short page
        3: [],
    }
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.params["country"] == "IN"
        return httpx.Response(200, json={"jobs": pages[int(request.url.params["page"])]})

    result = await HimalayasAdapter("IN", delay_seconds=0).fetch(client(handler), "himalayas", "")
    assert len(seen) == 3  # did not stop on the short page 2
    by_id = {p.source_id.rsplit("-", 1)[-1]: p for p in result.postings}
    assert sorted(by_id) == ["1", "2", "3", "5"]  # the expired job is skipped
    one = by_id["1"]
    assert one.source_url == "https://acme.example/apply/1"  # applicationLink, unchanged
    assert one.page_url == "https://himalayas.app/companies/acme/jobs/backend-1"
    assert normalise(one).work.scope == "worldwide"
    assert normalise(by_id["2"]).work.countries == ("IN", "SG")
    tz = normalise(by_id["3"]).work
    assert "IN" in tz.countries and "US" not in tz.countries
    assert normalise(by_id["5"]).salary.max_usd == 120_000  # type: ignore[union-attr]
    job = normalise(one)
    assert (job.source_quality, job.description_quality) == ("aggregator_full", "full")


async def test_himalayas_backs_off_on_429() -> None:
    calls = iter(
        [
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(200, json={"jobs": [himalayas_job(1)]}),
            httpx.Response(200, json={"jobs": []}),
        ]
    )
    result = await HimalayasAdapter(delay_seconds=0).fetch(
        client(lambda _: next(calls)), "himalayas", ""
    )
    assert len(result.postings) == 1


def test_timezone_list_to_countries() -> None:
    assert "IN" in countries_in_timezones([5.5])
    assert "US" in countries_in_timezones([-10, -9, -8, -7, -6, -5])
    assert "US" not in countries_in_timezones([-8, -7, -6, -5])  # Hawaii (-10) is outside


def test_a_timezone_list_with_gaps_does_not_admit_the_gap() -> None:
    # Shaped like a real Asia-Pacific listing: a few Pacific offsets, then +2 to +12.
    # Only the extremes span the Americas; no American offset is listed.
    offsets = [-11, -10, -9.5, -9, -8, 2, 3, 4, 5, 5.5, 5.75, 6, 6.5, 7, 8, 9, 10, 11, 12]
    countries = countries_in_timezones(offsets)
    assert "IN" in countries and "AU" in countries
    assert not {"BR", "AR", "CO", "GB"} & set(countries)


# timezoneRestrictions of rows 6, 26 and 27 of the 2026-11-24 Himalayas spot check
# (Invisible Technologies, Babou AI, Invisible Technologies): every offset there is.
EVERY_TIMEZONE = [-11, -10, -9.5, -9, -8, -7, -6, -5, -4, -3.5, -3, -2, -1, 0, 1, 2, 3, 3.5, 4]
EVERY_TIMEZONE += [4.5, 5, 5.5, 5.75, 6, 6.5, 7, 8, 8.75, 9, 9.5, 10, 10.5, 11, 12, 12.75, 13, 14]


async def test_himalayas_jobs_open_in_every_timezone_are_worldwide_not_a_country_list() -> None:
    jobs = [
        himalayas_job(6, title="GPU Kernels AI Task Auditor", timezoneRestrictions=EVERY_TIMEZONE),
        himalayas_job(26, title="Designer, AI Video", timezoneRestrictions=EVERY_TIMEZONE),
        himalayas_job(27, title="Arabic Voice Actor", timezoneRestrictions=EVERY_TIMEZONE),
        himalayas_job(28, timezoneRestrictions=[5, 5.5, 6]),  # a real restriction stays
    ]
    pages = iter([jobs, []])
    result = await HimalayasAdapter(delay_seconds=0).fetch(
        client(lambda _: httpx.Response(200, json={"jobs": next(pages)})), "himalayas", ""
    )
    assert len(countries_in_timezones(EVERY_TIMEZONE)) == len(utc_offsets())
    by_id = {p.source_id.rsplit("-", 1)[-1]: normalise(p) for p in result.postings}
    for i in ("6", "26", "27"):
        job = by_id[i]
        assert job.work.scope == "worldwide" and job.work.countries == ()
        assert job.location == WORLDWIDE == "Remote, worldwide"
    restricted = by_id["28"]
    assert restricted.work.scope == "listed" and "IN" in restricted.work.countries
    assert "US" not in restricted.work.countries


def adzuna_result(i: int, **overrides: Any) -> dict[str, Any]:
    item = {
        "id": str(i),
        "title": f"Data Engineer {i}",
        "description": "Spark and Airflow pipelines…",
        "redirect_url": f"https://www.adzuna.in/land/ad/{i}",
        "company": {"display_name": "Razorpay Software Private Limited"},
        "location": {"display_name": "Bengaluru, Karnataka", "area": ["India", "Karnataka"]},
        "created": "2026-11-20T10:00:00Z",
        "contract_time": "full_time",
        "salary_min": 1_800_000,
        "salary_max": 2_400_000,
        "salary_is_predicted": "0",
    }
    item.update(overrides)
    return item


LIMITS = {"minute": 25, "day": 250, "week": 1000, "month": 2500}


def usage_key(window: str) -> str:
    return adzuna_module.USAGE_KEY.format(window=window, period=periods(datetime.now(UTC))[window])


def adzuna(**kwargs: Any) -> AdzunaAdapter:
    values: dict[str, Any] = {
        "queries": ["data engineer"],
        "pages_per_query": 2,
        "limits": LIMITS,
        "stop_share": 0.8,
        "delay_seconds": 0,
        "backoff_seconds": 0,
    }
    values.update(kwargs)
    return AdzunaAdapter("app-id", "app-key", redis, **values)


async def test_adzuna_maps_results_counts_calls_and_ignores_predicted_salaries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/api/jobs/in/search/1"
        assert request.url.params["what"] == "data engineer"
        return httpx.Response(
            200,
            json={"results": [adzuna_result(1), adzuna_result(2, salary_is_predicted="1")]},
        )

    result = await adzuna().fetch(client(handler), "adzuna", "")
    one, two = result.postings
    assert one.source_url == "https://www.adzuna.in/land/ad/1"
    job = normalise(one)
    assert job.work.countries == ("IN",)
    assert (job.source_quality, job.description_quality) == ("aggregator_snippet", "snippet")
    assert job.salary is not None and job.salary.currency == "INR"
    assert normalise(two).salary is None  # Adzuna's estimate, not the employer's
    for window in LIMITS:  # one call, counted in every window; short page: no page 2
        assert int(await redis.get(usage_key(window))) == 1


@pytest.mark.parametrize(("window", "used"), [("day", 200), ("week", 800), ("month", 2000)])
async def test_adzuna_stops_at_80_percent_of_the_day_week_or_month(window: str, used: int) -> None:
    await redis.set(usage_key(window), used)

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no call may be made past the stop share")

    with pytest.raises(SourceError, match=f"{window} Adzuna calls at {used} of {LIMITS[window]}"):
        await adzuna().fetch(client(handler), "adzuna", "")


async def test_adzuna_waits_for_the_next_minute_at_80_percent_of_the_minute_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await redis.set(usage_key("minute"), 20)  # 80% of 25
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        await redis.delete(usage_key("minute"))  # the next minute starts empty

    monkeypatch.setattr("app.ingest.sources.adzuna.asyncio.sleep", sleep)
    result = await adzuna().fetch(
        client(lambda _: httpx.Response(200, json={"results": [adzuna_result(1)]})), "adzuna", ""
    )
    assert len(result.postings) == 1
    assert len(waits) == 1 and 0 < waits[0] <= 60.5


async def test_adzuna_backs_off_on_429_and_counts_every_call() -> None:
    calls = iter(
        [
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(200, json={"results": [adzuna_result(1)]}),
        ]
    )
    result = await adzuna().fetch(client(lambda _: next(calls)), "adzuna", "")
    assert len(result.postings) == 1
    assert int(await redis.get(usage_key("day"))) == 2  # the rejected call counts too


async def test_adzuna_gives_up_after_three_429s() -> None:
    with pytest.raises(SourceError, match="still rate-limited"):
        await adzuna().fetch(client(lambda _: httpx.Response(429)), "adzuna", "")


def test_usage_windows_are_keyed_by_utc_minute_day_iso_week_and_month() -> None:
    keys = Usage(redis, LIMITS, 0.8).keys(datetime(2026, 12, 31, 23, 59, tzinfo=UTC))
    assert keys == {
        "minute": "adzuna:calls:minute:20261231T2359",
        "day": "adzuna:calls:day:20261231",
        "week": "adzuna:calls:week:2026W53",
        "month": "adzuna:calls:month:202612",
    }


async def test_adzuna_errors_never_include_the_key_bearing_url() -> None:
    with pytest.raises(SourceError) as error:
        await adzuna().fetch(client(lambda _: httpx.Response(401)), "adzuna", "")
    assert "app-key" not in str(error.value) and "HTTP 401" in str(error.value)


async def test_smartrecruiters_lists_then_fetches_each_posting() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/postings"):
            return httpx.Response(
                200,
                json={
                    "totalFound": 2,
                    "content": [{"id": "111", "name": "A"}, {"id": "222", "name": "B"}],
                },
            )
        posting_id = request.url.path.rsplit("/", 1)[-1]
        if posting_id == "222":
            return httpx.Response(404)  # one missing posting must not fail the board
        return httpx.Response(
            200,
            json={
                "id": "111",
                "name": "Site Reliability Engineer",
                "company": {"name": "Acme"},
                "releasedDate": "2026-11-20T10:00:00.000Z",
                "location": {"city": "Pune", "country": "in", "remote": False, "hybrid": True},
                "typeOfEmployment": {"label": "Full-time"},
                "postingUrl": "https://jobs.smartrecruiters.com/Acme/111",
                "jobAd": {
                    "sections": {
                        "companyDescription": {"title": "About", "text": "<p>We are Acme</p>"},
                        "jobDescription": {"title": "Role", "text": "<p>Kubernetes, Go</p>"},
                    }
                },
                "compensation": {
                    "min": 2_000_000,
                    "max": 3_000_000,
                    "currency": "INR",
                    "period": "YEAR",
                },
            },
        )

    result = await SmartRecruitersAdapter().fetch(client(handler), "Acme", "Acme")
    (posting,) = result.postings
    job = normalise(posting)
    assert job.title == "Site Reliability Engineer"
    assert "We are Acme" not in job.description and "Kubernetes" in job.description
    assert job.work.countries == ("IN",) and job.remote_policy == "hybrid"
    assert job.salary is not None and job.salary.max == 3_000_000
    assert job.source_quality == "ats_direct"


async def test_workable_and_recruitee() -> None:
    def workable(request: httpx.Request) -> httpx.Response:
        assert request.url.params["details"] == "true"
        return httpx.Response(
            200,
            json={
                "name": "Acme",
                "jobs": [
                    {
                        "title": "QA Engineer",
                        "shortcode": "AB12",
                        "country": "India",
                        "city": "Chennai",
                        "workplace_type": "on_site",
                        "url": "https://apply.workable.com/acme/j/AB12/",
                        "description": "<p>Selenium</p>",
                        "published_on": "2026-11-18",
                    }
                ],
            },
        )

    (w,) = (await WorkableAdapter().fetch(client(workable), "acme", "Acme")).postings
    assert normalise(w).work.countries == ("IN",) and normalise(w).remote_policy == "onsite"

    def recruitee(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "offers": [
                    {
                        "id": 7,
                        "title": "Designer",
                        "status": "published",
                        "careers_url": "https://acme.recruitee.com/o/designer",
                        "description": "<p>Figma</p>",
                        "requirements": "<p>3 years</p>",
                        "remote": True,
                        "locations": [{"city": "Remote", "country_code": "IN"}],
                        "salary": {
                            "min": "1500000",
                            "max": "2000000",
                            "period": "year",
                            "currency": "INR",
                        },
                        "published_at": "2026-11-18 10:00:00 UTC",
                    },
                    {"id": 8, "title": "Draft", "status": "draft"},
                ]
            },
        )

    (r,) = (await RecruiteeAdapter().fetch(client(recruitee), "acme", "Acme")).postings
    job = normalise(r)
    assert job.remote_policy == "remote" and job.work.countries == ("IN",)
    assert job.salary is not None and job.salary.min == 1_500_000


def test_aggregator_company_names_match_known_companies() -> None:
    assert match_key("Razorpay Software Private Limited") == match_key("Razorpay")
    assert match_key("Acme Technologies Pvt. Ltd.") == match_key("ACME")
    assert match_key("AI") == "ai"  # never stripped to nothing
    assert json.dumps(match_key("Zeta")) == '"zeta"'


def test_utc_offset_table_keys_are_country_codes() -> None:
    """YAML reads a bare NO (Norway) as the boolean false; every key must be a code."""
    from app.ingest.countries import gazetteer
    from app.ingest.sources.himalayas import utc_offsets

    offsets = utc_offsets()
    assert all(isinstance(code, str) and len(code) == 2 for code in offsets)
    assert set(offsets) <= gazetteer().codes
    assert "NO" in offsets
    assert countries_in_timezones([0, 1, 2])  # sorts without a bool among the keys
