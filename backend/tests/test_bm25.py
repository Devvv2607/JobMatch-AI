"""BM25: build from the pool, masked search, publish and hot swap."""

import asyncio
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis
from app.retrieval.bm25 import VERSION_KEY, Bm25Holder, build_index, load_index, publish, rebuild
from tests.search_helpers import add_company, add_job


async def seed(session: AsyncSession) -> dict[str, uuid.UUID]:
    company = await add_company(session, "Acme")
    jobs = {
        "cpp": await add_job(session, company, "C++ Developer", "Low-latency C++ trading systems"),
        "csharp": await add_job(session, company, "C# Engineer", "ASP.NET services in C#"),
        "python": await add_job(
            session, company, "Python Engineer", "Building APIs", skills=["Python", "FastAPI"]
        ),
        "chef": await add_job(session, company, "Pastry Chef", "Croissants and laminated dough"),
    }
    await add_job(session, company, "Expired Python role", "Python", status="expired")
    await session.commit()
    return {k: v.id for k, v in jobs.items()}


async def test_index_holds_the_pool_and_keeps_cpp_and_csharp_as_tokens(
    session: AsyncSession, tmp_path: Path
) -> None:
    ids = await seed(session)
    version, documents = await build_index(session, tmp_path)
    assert documents == 4  # the expired job is not indexed
    index = load_index(tmp_path / version)
    assert [hit for hit, _ in index.search("c++", 5)] == [ids["cpp"]]
    assert [hit for hit, _ in index.search("C#", 5)] == [ids["csharp"]]
    # Stemming: "developers" finds "Developer"; skills are indexed too.
    assert index.search("developers", 5)[0][0] == ids["cpp"]
    assert index.search("fastapi", 5)[0][0] == ids["python"]


async def test_mask_limits_hits_and_zero_scores_are_dropped(
    session: AsyncSession, tmp_path: Path
) -> None:
    ids = await seed(session)
    version, _ = await build_index(session, tmp_path)
    index = load_index(tmp_path / version)
    assert index.search("python engineer", 10, allowed={ids["chef"]}) == []
    hits = index.search("engineer", 10, allowed={ids["python"], ids["chef"]})
    assert [hit for hit, _ in hits] == [ids["python"]]
    assert index.search("quantum", 10) == []  # word not in the vocabulary
    assert index.search("   ", 10) == []
    assert index.search("engineer", 10, allowed=set()) == []


async def test_empty_pool_builds_an_empty_index(session: AsyncSession, tmp_path: Path) -> None:
    version, documents = await build_index(session, tmp_path)
    assert documents == 0
    assert load_index(tmp_path / version).search("anything", 10) == []


async def test_holder_swaps_to_a_newly_published_index(
    session: AsyncSession, tmp_path: Path
) -> None:
    ids = await seed(session)
    holder = Bm25Holder(tmp_path, redis, check_seconds=0)
    assert await holder.current() is None  # nothing published yet

    first, _, _ = await rebuild(session, redis, tmp_path)
    index = await holder.current()
    assert index is not None and index.version == first
    assert index.search("croissants", 5)[0][0] == ids["chef"]

    company = await add_company(session, "Bakery")
    baker = await add_job(session, company, "Baker", "Sourdough and croissants")
    await session.commit()
    second, documents, _ = await rebuild(session, redis, tmp_path)
    assert documents == 5 and second != first

    held = index  # a search that started on the old index keeps it
    swapped = await holder.current()
    assert swapped is not None and swapped.version == second
    assert baker.id in {hit for hit, _ in swapped.search("croissants", 5)}
    assert baker.id not in {hit for hit, _ in held.search("croissants", 5)}


async def test_publish_keeps_the_newest_two_versions(session: AsyncSession, tmp_path: Path) -> None:
    await seed(session)
    versions = [(await build_index(session, tmp_path))[0] for _ in range(3)]
    stale = tmp_path / ".tmp-crashed"
    stale.mkdir()
    await publish(redis, tmp_path, versions[-1])
    remaining = sorted(p.name for p in await asyncio.to_thread(lambda: list(tmp_path.iterdir())))
    assert remaining == [".tmp-crashed", *versions[-2:]]  # a recent staging dir is left
    assert await redis.get(VERSION_KEY) in (versions[-1], versions[-1].encode())


async def test_holder_ignores_a_version_missing_on_disk(tmp_path: Path) -> None:
    await redis.set(VERSION_KEY, "19700101T000000000000Z")
    holder = Bm25Holder(tmp_path, redis, check_seconds=0)
    assert await holder.current() is None
