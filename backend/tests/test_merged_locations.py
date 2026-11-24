"""A job merged from several postings stays findable from every posting's location and
eligibility, and the API shows every location (the 2026-11-24 spot check: Swiggy's
"Sales Manager I" in Baddi, Sikar, ...).

The first test runs a real ingest with three near-duplicate postings; the others build
a canonical job and its duplicate directly and call the search API."""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.search import get_search_engine
from app.core.redis import redis
from app.ingest.dedup import _alternate_sources
from app.main import app
from app.models import Job
from app.retrieval.bm25 import Bm25Holder, rebuild
from app.retrieval.filters import allowed_ids
from app.retrieval.rules import LocationRule, WorkEligibility
from app.retrieval.service import SearchEngine
from tests.helpers import bearer, register
from tests.search_helpers import BagEmbedder, OverlapReranker, add_company, add_job
from tests.test_ingest_pipeline import (
    BODY,
    T0,
    CountingEmbedder,
    ScriptedAdapter,
    adapters,  # noqa: F401 - fixture
    ingest,
    jobs,
    raw,
)


@pytest.mark.slow
async def test_a_merged_job_carries_every_variants_location_for_filtering(
    adapters: dict[str, ScriptedAdapter],  # noqa: F811
    session: AsyncSession,
) -> None:
    cities = {"s1": "Baddi, HP, IN", "s2": "Sikar, RJ, IN", "s3": "Pune, MH, IN"}
    adapters["greenhouse"].boards = {
        "acme": [
            raw(sid, title="Sales Manager I", description_html=BODY.format(city=""), locations=[c])
            for sid, c in cities.items()
        ]
    }
    await ingest(adapters, CountingEmbedder(), T0)

    rows = await jobs(session)
    canonical = next(rows[s] for s in cities if rows[s].duplicate_of is None)
    hidden = [rows[s] for s in cities if rows[s].duplicate_of is not None]
    assert len(hidden) == 2
    assert sorted(canonical.all_locations) == sorted(cities.values())
    assert canonical.all_locations[0] == canonical.location  # its own first
    assert canonical.all_work_countries == ["IN"]

    for place in ("Sikar", "sikar", "Baddi", "Pune, MH"):
        found = set(await allowed_ids(session, [LocationRule(places=[place])]))
        assert found == {canonical.id}, place  # the canonical job, never a hidden duplicate
    assert not await allowed_ids(session, [LocationRule(places=["Jaipur"])])
    assert canonical.id in await allowed_ids(session, [WorkEligibility(country="IN")])


@pytest.fixture
async def merged(session: AsyncSession) -> dict[str, uuid.UUID]:
    """A US posting kept as canonical, with an India posting of the same role merged in."""
    company = await add_company(session, "Globex")
    us = await add_job(
        session,
        company,
        "Platform Engineer",
        "Kubernetes platform team",
        skills=["Kubernetes"],
        location="New York, NY",
        work_countries=["US"],
        eligibility_scope="listed",
    )
    india = await add_job(
        session,
        company,
        "Platform Engineer",
        "Kubernetes platform team",
        skills=["Kubernetes"],
        location="Bengaluru, India",
        work_countries=["IN"],
        eligibility_scope="listed",
        duplicate_of=us.id,
        duplicate_reason="content_hash",
    )
    other = await add_job(
        session, company, "Kubernetes Engineer", "Kubernetes", skills=["Kubernetes"]
    )
    await session.flush()
    await _alternate_sources(session)
    await session.commit()
    return {"us": us.id, "india": india.id, "other": other.id}


@pytest.fixture
async def engine(
    session: AsyncSession, merged: dict[str, uuid.UUID], tmp_path: Path
) -> AsyncIterator[SearchEngine]:
    await rebuild(session, redis, tmp_path)
    engine = SearchEngine(BagEmbedder(), OverlapReranker(), Bm25Holder(tmp_path, redis, 0))
    app.dependency_overrides[get_search_engine] = lambda: engine
    yield engine
    app.dependency_overrides.pop(get_search_engine, None)
    engine.close()


async def search(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    auth = bearer(await register(client, f"{uuid.uuid4().hex[:8]}@example.com"))
    response = await client.post("/api/v1/search", json=body, headers=auth)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_the_union_is_stored_on_the_canonical_job(
    session: AsyncSession, merged: dict[str, uuid.UUID]
) -> None:
    canonical = await session.scalar(select(Job).where(Job.id == merged["us"]))
    assert canonical is not None
    assert canonical.all_locations == ["New York, NY", "Bengaluru, India"]
    assert canonical.all_work_countries == ["IN", "US"]


async def test_an_india_candidate_finds_the_merged_job_and_sees_the_india_location_first(
    client: httpx.AsyncClient, engine: SearchEngine, merged: dict[str, uuid.UUID]
) -> None:
    rules = [{"kind": "work_eligibility", "country": "IN"}]
    body = await search(client, query="platform engineer kubernetes", rules=rules, limit=10)
    job = next(r["job"] for r in body["results"] if r["job"]["id"] == str(merged["us"]))
    assert job["location"] == "Bengaluru, India"
    assert job["locations"] == ["Bengaluru, India", "New York, NY"]
    assert str(merged["india"]) not in {r["job"]["id"] for r in body["results"]}


async def test_without_a_candidate_country_the_jobs_own_location_comes_first(
    client: httpx.AsyncClient, engine: SearchEngine, merged: dict[str, uuid.UUID]
) -> None:
    body = await search(client, query="platform engineer kubernetes", limit=10)
    job = next(r["job"] for r in body["results"] if r["job"]["id"] == str(merged["us"]))
    assert job["location"] == "New York, NY"
    assert job["locations"] == ["New York, NY", "Bengaluru, India"]


async def test_a_location_filter_and_a_location_word_both_find_the_merged_job(
    client: httpx.AsyncClient, engine: SearchEngine, merged: dict[str, uuid.UUID]
) -> None:
    rules = [{"kind": "location", "places": ["bengaluru"]}]
    body = await search(client, query="kubernetes", rules=rules, limit=10)
    assert [r["job"]["id"] for r in body["results"]] == [str(merged["us"])]
    # BM25 indexes every location: the city name alone ranks the merged job.
    body = await search(client, query="bengaluru", limit=10)
    assert body["results"] and body["results"][0]["job"]["id"] == str(merged["us"])
