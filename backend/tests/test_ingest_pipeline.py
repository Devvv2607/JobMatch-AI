"""The full run against the test database, with scripted adapters and a counting
embedder: inserts, incremental embedding, updates, misses, expiry, staleness, dedup."""

import hashlib
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.ingest.companies import CompanyEntry
from app.ingest.runner import RunSummary, run_ingest
from app.ingest.sources.base import SourceError
from app.ingest.types import BoardResult, RawPosting
from app.models import Company, IngestRun, Job

T0 = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
NEAR_DUPLICATES_OFF = get_settings().model_copy(update={"ingest_near_duplicates_enabled": False})
COMPANIES = [
    CompanyEntry("Acme", "greenhouse", "acme", ("ai",)),
    CompanyEntry("Globex", "greenhouse", "globex", ("fintech",)),
]


def raw(source_id: str, **overrides: Any) -> RawPosting:
    fields: dict[str, Any] = {
        "source": "greenhouse",
        "source_id": source_id,
        "company_name": "Acme",
        "title": f"Engineer {source_id}",
        "source_url": f"https://example.com/{source_id}",
        "description_html": f"<p>Role {source_id}. Python and PostgreSQL.</p>",
        "locations": ["Bengaluru, India"],
        "workplace": "onsite",
        "posted_at": T0,
    }
    fields.update(overrides)
    return RawPosting(**fields)


class ScriptedAdapter:
    """Returns the postings (or error) set for each board."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.boards: dict[str, list[RawPosting] | SourceError] = {}
        self.calls = 0

    async def fetch(self, http: httpx.AsyncClient, board: str, company_name: str) -> BoardResult:
        self.calls += 1
        result = self.boards.get(board, [])
        if isinstance(result, SourceError):
            raise result
        return BoardResult(board, list(result))


class CountingEmbedder:
    """Deterministic unit vectors. Texts containing a `twin:<name>` marker embed to the
    same direction (cosine ~1); everything else is effectively orthogonal."""

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        marker = next((w for w in text.split() if w.startswith("twin:")), text)
        digest = hashlib.sha256(marker.encode()).digest() * 12
        values = [b - 127.5 for b in digest[:384]]
        norm = math.sqrt(sum(v * v for v in values))
        return [v / norm for v in values]


@pytest.fixture
def adapters() -> dict[str, ScriptedAdapter]:
    return {s: ScriptedAdapter(s) for s in ("greenhouse", "lever", "ashby", "remotive")}


async def ingest(
    adapters: dict[str, ScriptedAdapter],
    embedder: CountingEmbedder,
    now: datetime,
    sources: tuple[str, ...] = ("greenhouse",),
    settings: Settings | None = None,
) -> RunSummary:
    async with httpx.AsyncClient() as http:
        return await run_ingest(
            SessionLocal,
            http,
            embedder,
            COMPANIES,
            settings or get_settings(),
            sources=sources,
            adapters=adapters,
            now=now,
        )


def assert_group(rows: dict[str, Job], ids: list[str], reason: str) -> Job:
    """Exactly one of `ids` is canonical and every other one points to it."""
    group = [rows[i] for i in ids]
    canonical = [j for j in group if j.duplicate_of is None]
    assert len(canonical) == 1, [(j.source_id, j.duplicate_of) for j in group]
    for job in group:
        if job is not canonical[0]:
            assert job.duplicate_of == canonical[0].id
            assert job.duplicate_reason == reason
    return canonical[0]


async def jobs(session: AsyncSession) -> dict[str, Job]:
    session.expire_all()
    return {j.source_id: j for j in await session.scalars(select(Job))}


async def test_first_run_inserts_normalised_jobs_and_records_the_run(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    adapters["greenhouse"].boards = {
        "acme": [raw("1"), raw("2", locations=["Remote - US"], workplace="remote")],
        "globex": [raw("3", company_name="Globex")],
    }
    embedder = CountingEmbedder()

    summary = await ingest(adapters, embedder, T0)

    rows = await jobs(session)
    assert set(rows) == {"1", "2", "3"}
    one = rows["1"]
    assert one.status == "live" and one.missed_runs == 0
    assert one.work_countries == ["IN"] and one.eligibility_scope == "listed"
    assert one.eligibility_source == "location:greenhouse.location:city"
    assert one.skills == ["Python", "PostgreSQL"]
    assert one.first_seen_at == one.last_seen_at == one.content_changed_at == T0
    assert one.embedding is not None and one.embedded_hash == one.embed_input_hash
    assert one.search_text == "Role 1. Python and PostgreSQL."
    assert rows["2"].work_countries == ["US"]
    companies = {c.slug: c for c in await session.scalars(select(Company))}
    assert rows["3"].company_id == companies["globex"].id
    assert companies["globex"].industries == ["fintech"]

    run = summary.sources["greenhouse"]
    assert (run.status, run.boards_ok, run.fetched, run.new) == ("succeeded", 2, 3, 3)
    assert (run.embedded, run.embed_pending, run.error) == (3, 0, None)
    assert run.finished_at is not None
    assert summary.embedded == 3
    assert await session.scalar(select(func.count()).select_from(IngestRun)) == 1


async def test_second_run_embeds_nothing_and_a_change_re_embeds_only_that_job(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    adapters["greenhouse"].boards = {"acme": [raw("1"), raw("2")]}
    embedder = CountingEmbedder()
    await ingest(adapters, embedder, T0)
    assert len(embedder.embedded) == 2

    second = await ingest(adapters, embedder, T0 + timedelta(hours=12))
    assert second.embedded == 0
    assert len(embedder.embedded) == 2  # the model was not called again
    assert second.sources["greenhouse"].unchanged == 2

    adapters["greenhouse"].boards = {
        "acme": [raw("1"), raw("2", description_html="<p>Now with Rust.</p>")]
    }
    third = await ingest(adapters, embedder, T0 + timedelta(days=1))
    assert third.embedded == 1
    assert "Now with Rust." in embedder.embedded[-1]
    rows = await jobs(session)
    assert rows["2"].status == "updated"
    assert rows["2"].content_changed_at == T0 + timedelta(days=1)
    assert rows["2"].skills == ["Rust"]
    assert rows["1"].status == "live"

    fourth = await ingest(adapters, embedder, T0 + timedelta(days=2))
    assert fourth.embedded == 0
    assert (await jobs(session))["2"].status == "live"  # "updated" lasts one run


async def test_jobs_missing_from_two_consecutive_runs_expire(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    gh = adapters["greenhouse"]
    gh.boards = {"acme": [raw("1"), raw("2")]}
    embedder = CountingEmbedder()
    await ingest(adapters, embedder, T0)

    gh.boards = {"acme": [raw("1")]}
    first_miss = await ingest(adapters, embedder, T0 + timedelta(hours=12))
    row = (await jobs(session))["2"]
    assert (row.status, row.missed_runs) == ("live", 1)
    assert first_miss.sources["greenhouse"].expired == 0

    second_miss = await ingest(adapters, embedder, T0 + timedelta(days=1))
    row = (await jobs(session))["2"]
    assert (row.status, row.missed_runs) == ("expired", 2)
    assert second_miss.sources["greenhouse"].expired == 1

    gh.boards = {"acme": [raw("1"), raw("2")]}
    await ingest(adapters, embedder, T0 + timedelta(days=2))
    row = (await jobs(session))["2"]
    assert (row.status, row.missed_runs) == ("live", 0)  # back on the board


async def test_a_failed_board_fetch_does_not_count_as_a_miss(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    gh = adapters["greenhouse"]
    gh.boards = {"acme": [raw("1")], "globex": [raw("9", company_name="Globex")]}
    embedder = CountingEmbedder()
    await ingest(adapters, embedder, T0)

    gh.boards = {"acme": SourceError("HTTP 503"), "globex": [raw("9", company_name="Globex")]}
    for hours in (12, 24, 36):
        summary = await ingest(adapters, embedder, T0 + timedelta(hours=hours))

    row = (await jobs(session))["1"]
    assert (row.status, row.missed_runs) == ("live", 0)
    run = summary.sources["greenhouse"]
    assert (run.status, run.boards_ok, run.boards_failed) == ("partial", 1, 1)
    assert run.error == "fetch: 1 boards failed"
    assert run.failures == [{"board": "acme", "error": "HTTP 503"}]


async def test_a_source_where_every_board_failed_is_marked_failed(
    adapters: dict[str, ScriptedAdapter],
) -> None:
    adapters["greenhouse"].boards = {
        "acme": SourceError("board not found (HTTP 404)"),
        "globex": SourceError("HTTP 500"),
    }
    summary = await ingest(adapters, CountingEmbedder(), T0)
    run = summary.sources["greenhouse"]
    assert (run.status, run.boards_failed, run.fetched) == ("failed", 2, 0)
    assert run.error == "fetch: no board could be fetched"


async def test_a_posting_that_fails_to_normalise_is_skipped_not_fatal(
    adapters: dict[str, ScriptedAdapter],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingest.normalise import normalise as real

    def flaky(posting: RawPosting) -> Any:
        if posting.source_id == "bad":
            raise ValueError("unparseable")
        return real(posting)

    monkeypatch.setattr("app.ingest.runner.normalise", flaky)
    adapters["greenhouse"].boards = {"acme": [raw("1"), raw("bad")]}
    summary = await ingest(adapters, CountingEmbedder(), T0)

    assert set(await jobs(session)) == {"1"}
    run = summary.sources["greenhouse"]
    assert run.skipped == 1 and run.boards_failed == 0
    assert (run.status, run.error) == ("partial", "normalise: 1 postings skipped")
    assert "unparseable" in run.failures[0]["error"]


async def test_old_unchanged_jobs_become_stale_and_a_change_revives_them(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    gh = adapters["greenhouse"]
    gh.boards = {"acme": [raw("old", posted_at=T0 - timedelta(days=60)), raw("new")]}
    embedder = CountingEmbedder()
    await ingest(adapters, embedder, T0)
    assert (await jobs(session))["old"].status == "live"  # content first seen just now

    later = T0 + timedelta(days=46)
    summary = await ingest(adapters, embedder, later)
    rows = await jobs(session)
    assert rows["old"].status == "stale"
    assert rows["new"].status == "stale"  # posted T0, unchanged for 46 days
    assert summary.stale == 2

    gh.boards = {
        "acme": [raw("old", posted_at=T0 - timedelta(days=60), title="Engineer v2"), raw("new")]
    }
    await ingest(adapters, embedder, later + timedelta(days=1))
    rows = await jobs(session)
    assert rows["old"].status == "updated"
    assert rows["new"].status == "stale"  # still unchanged: stays stale


async def test_jobs_without_posted_at_age_from_first_seen(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    adapters["greenhouse"].boards = {"acme": [raw("1", posted_at=None)]}
    embedder = CountingEmbedder()
    await ingest(adapters, embedder, T0)
    await ingest(adapters, embedder, T0 + timedelta(days=44))
    assert (await jobs(session))["1"].status == "live"
    await ingest(adapters, embedder, T0 + timedelta(days=46))
    assert (await jobs(session))["1"].status == "stale"


async def test_exact_duplicates_by_content_hash_and_by_title_and_location(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    same = {"title": "Data Engineer", "description_html": "<p>Same text.</p>"}
    adapters["greenhouse"].boards = {
        "acme": [
            raw("a1", **same),
            raw("a2", **same),  # identical content: content_hash duplicate of a1
            raw("a3", title="Data Engineer", description_html="<p>Other team.</p>"),
            # Same text, other Indian city: not an exact duplicate (checked with the text
            # pass off), but "also posted in Pune" by the text pass (next test file block).
            raw("a4", **same, locations=["Pune, India"]),
        ],
        "globex": [raw("g1", company_name="Globex", **same)],  # other company: not a duplicate
    }
    summary = await ingest(adapters, CountingEmbedder(), T0, settings=NEAR_DUPLICATES_OFF)

    rows = await jobs(session)
    # a1 and a2 share a content hash; a3 shares title and location with them. All three
    # are one posting: exactly one original, the other two pointing straight at it.
    group = [rows[i] for i in ("a1", "a2", "a3")]
    originals = [j for j in group if j.duplicate_of is None]
    assert len(originals) == 1
    assert {j.duplicate_of for j in group if j.duplicate_of} == {originals[0].id}
    assert {j.duplicate_reason for j in group if j.duplicate_of} <= {
        "content_hash",
        "title_location",
    }
    assert rows["a4"].duplicate_of is None
    assert rows["g1"].duplicate_of is None
    assert summary.duplicates["content_hash"] == 1
    assert summary.duplicates["title_location"] == 1


WITH_ADZUNA = get_settings().model_copy(update={"adzuna_app_id": "x", "adzuna_app_key": "y"})
# Thirty-odd shared words: one changed word keeps the word-set overlap above 0.9.
BODY = (
    "<p>Build and run the payments ledger with Python and PostgreSQL. You will own "
    "services end to end, write design docs, review code, mentor engineers, improve "
    "reliability, reduce latency, ship weekly and work with product and finance teams "
    "on reconciliation, settlement and reporting. Team in {city}.</p>"
)


async def test_text_near_duplicates_need_the_same_title_and_the_same_eligibility(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    adapters["greenhouse"].boards = {
        "acme": [
            raw("n1", title="Backend Engineer", description_html=BODY.format(city="Bengaluru")),
            raw(
                "n2",
                title="Backend Engineer",
                description_html=BODY.format(city="Hyderabad"),
                locations=["Hyderabad, India"],
            ),
            # Same text, but a US role: an India candidate must still see n1, and a US
            # candidate must still see this one.
            raw(
                "n3",
                title="Backend Engineer",
                description_html=BODY.format(city="Austin"),
                locations=["Austin, TX"],
            ),
            # Same eligibility, different title: a different role.
            raw("n4", title="Frontend Engineer", description_html=BODY.format(city="Pune")),
        ],
        "globex": [
            raw(
                "g1",
                company_name="Globex",
                title="Backend Engineer",
                description_html=BODY.format(city="Bengaluru"),
            ),
        ],
    }
    summary = await ingest(adapters, CountingEmbedder(), T0)

    rows = await jobs(session)
    canonical = assert_group(rows, ["n1", "n2"], "near_duplicate_text")
    assert rows["n3"].duplicate_of is None
    assert rows["n4"].duplicate_of is None
    assert rows["g1"].duplicate_of is None
    assert summary.duplicates["near_duplicate_text"] == 1
    (alternate,) = canonical.alternate_sources  # "also posted in Hyderabad"
    assert alternate["reason"] == "near_duplicate_text"
    assert alternate["location"] in ("Hyderabad, India", "Bengaluru, India")


async def test_text_near_duplicates_can_be_turned_off_and_old_marks_are_cleared(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    adapters["greenhouse"].boards = {
        "acme": [
            raw("n1", title="Backend Engineer", description_html=BODY.format(city="Bengaluru")),
            raw(
                "n2",
                title="Backend Engineer",
                description_html=BODY.format(city="Chennai"),
                locations=["Chennai, India"],
            ),
            raw("e1", title="Data Engineer", description_html="<p>Same.</p>"),
            raw("e2", title="Data Engineer", description_html="<p>Same.</p>"),
        ]
    }
    embedder = CountingEmbedder()
    marked = await ingest(adapters, embedder, T0)
    assert marked.duplicates["near_duplicate_text"] == 1

    later = await ingest(adapters, embedder, T0 + timedelta(hours=12), settings=NEAR_DUPLICATES_OFF)
    rows = await jobs(session)
    assert rows["n1"].duplicate_of is None and rows["n2"].duplicate_of is None
    assert "near_duplicate_text" not in later.duplicates
    assert later.duplicates["content_hash"] == 1  # exact dedup still runs
    assert_group(rows, ["e1", "e2"], "content_hash")
    assert all(j.alternate_sources == [] for j in rows.values() if j.source_id.startswith("n"))


async def test_cross_source_duplicates_keep_the_company_ats_posting(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    """An Adzuna snippet of the company's own ATS posting is the same job; the ATS one is
    canonical even though Adzuna was seen first."""
    adapters["adzuna"] = ScriptedAdapter("adzuna")
    adapters["adzuna"].boards = {
        "adzuna": [
            raw(
                "az1",
                source="adzuna",
                company_name="Acme Technologies Private Limited",
                title="Backend Engineer",
                source_url="https://www.adzuna.in/land/ad/az1",
                # The first ~40 words of the same posting, cut off.
                description_html=BODY.format(city="Bengaluru")[:220] + "…",
                locations=["Bengaluru, Karnataka"],  # Adzuna's form of the same place
                workplace=None,
            )
        ]
    }
    adapters["greenhouse"].boards = {
        "acme": [
            raw("gh1", title="Backend Engineer", description_html=BODY.format(city="Bengaluru"))
        ]
    }
    await ingest(adapters, CountingEmbedder(), T0, sources=("adzuna",), settings=WITH_ADZUNA)
    summary = await ingest(
        adapters, CountingEmbedder(), T0 + timedelta(hours=1), sources=("greenhouse",)
    )
    rows = await jobs(session)
    assert rows["az1"].company_id == rows["gh1"].company_id  # matched by the looser key
    canonical = assert_group(rows, ["gh1", "az1"], "cross_source")
    assert canonical.source == "greenhouse"
    assert canonical.alternate_sources[0]["source"] == "adzuna"
    assert summary.duplicates["cross_source"] == 1


async def test_buckets_over_the_cap_are_skipped(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.ingest.dedup.MAX_BUCKET", 2)
    adapters["greenhouse"].boards = {
        "acme": [
            raw(
                f"b{i}",
                title="Backend Engineer",
                description_html=BODY.format(city=city),
                locations=[f"{city}, India"],
            )
            for i, city in enumerate(("Bengaluru", "Chennai", "Pune"))
        ]
    }
    summary = await ingest(adapters, CountingEmbedder(), T0)
    assert summary.duplicates["text_buckets_skipped"] == 1
    assert "near_duplicate_text" not in summary.duplicates or (
        summary.duplicates["near_duplicate_text"] == 0
    )


async def test_dedup_is_recomputed_when_the_canonical_job_expires(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    same = {"title": "Data Engineer", "description_html": "<p>Same text.</p>"}
    gh = adapters["greenhouse"]
    # a1 was posted earlier, so it wins the tie between postings first seen together.
    gh.boards = {"acme": [raw("a1", **same, posted_at=T0 - timedelta(days=3)), raw("a2", **same)]}
    embedder = CountingEmbedder()
    await ingest(adapters, embedder, T0)
    assert (await jobs(session))["a2"].duplicate_of == (await jobs(session))["a1"].id

    gh.boards = {"acme": [raw("a2", **same)]}
    await ingest(adapters, embedder, T0 + timedelta(hours=12))
    await ingest(adapters, embedder, T0 + timedelta(days=1))
    rows = await jobs(session)
    assert rows["a1"].status == "expired"
    assert rows["a2"].duplicate_of is None  # now the surviving original


async def test_remotive_jobs_create_companies_and_respect_the_fetch_interval(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    adapters["remotive"].boards = {
        "remotive": [
            raw(
                "r1",
                source="remotive",
                company_name="Lemon.io",
                locations=["Worldwide"],
                workplace="remote",
                source_url="https://remotive.com/remote-jobs/x-r1",
            ),
        ]
    }
    embedder = CountingEmbedder()
    first = await ingest(adapters, embedder, T0, sources=("remotive",))
    assert first.sources["remotive"].status == "succeeded"
    row = (await jobs(session))["r1"]
    assert row.eligibility_scope == "worldwide"
    company = await session.get(Company, row.company_id)
    assert company is not None and company.ats is None and company.industries == []

    too_soon = await ingest(adapters, embedder, T0 + timedelta(hours=2), sources=("remotive",))
    assert too_soon.sources["remotive"].status == "skipped"
    assert "fetched at most every 6:00:00" in (too_soon.sources["remotive"].note or "")
    assert adapters["remotive"].calls == 1

    later = await ingest(adapters, embedder, T0 + timedelta(hours=7), sources=("remotive",))
    assert later.sources["remotive"].status == "succeeded"
    assert adapters["remotive"].calls == 2


async def test_a_remotive_posting_from_a_configured_company_joins_that_company(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    adapters["greenhouse"].boards = {"acme": [raw("1")]}
    adapters["remotive"].boards = {
        "remotive": [raw("r1", source="remotive", company_name="Acme, Inc.", workplace="remote")]
    }
    await ingest(adapters, CountingEmbedder(), T0, sources=("greenhouse", "remotive"))
    rows = await jobs(session)
    assert rows["r1"].company_id == rows["1"].company_id


async def test_one_ingest_runs_row_per_source_per_run(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    summary = await ingest(
        adapters, CountingEmbedder(), T0, sources=("greenhouse", "lever", "ashby", "remotive")
    )
    runs = (await session.scalars(select(IngestRun))).all()
    assert sorted(r.source for r in runs) == ["ashby", "greenhouse", "lever", "remotive"]
    assert {r.run_id for r in runs} == {summary.run_id}
    assert all(r.finished_at is not None for r in runs)


async def test_expired_jobs_are_not_embedded(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    adapters["greenhouse"].boards = {"acme": [raw("1")]}
    embedder = CountingEmbedder()
    await ingest(adapters, embedder, T0)
    await session.execute(
        update(Job).values(status="expired", embedded_hash=None, description="changed")
    )
    await session.commit()
    adapters["greenhouse"].boards = {"acme": []}
    summary = await ingest(adapters, embedder, T0 + timedelta(hours=12))
    assert summary.embedded == 0


async def test_embedding_runs_in_small_batches(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    from app.ingest.embed import BATCH_SIZE

    class BatchRecorder(CountingEmbedder):
        def __init__(self) -> None:
            super().__init__()
            self.batch_sizes: list[int] = []

        def embed(self, texts: list[str]) -> list[list[float]]:
            self.batch_sizes.append(len(texts))
            return super().embed(texts)

    adapters["greenhouse"].boards = {"acme": [raw(str(i)) for i in range(BATCH_SIZE * 2 + 3)]}
    embedder = BatchRecorder()
    summary = await ingest(adapters, embedder, T0)

    assert summary.embedded == BATCH_SIZE * 2 + 3
    assert embedder.batch_sizes == [BATCH_SIZE, BATCH_SIZE, 3]
    rows = await jobs(session)
    assert all(
        j.embedding is not None and j.embedded_hash == j.embed_input_hash for j in rows.values()
    )


# --- run status covers every stage ----------------------------------------------------


class FailingEmbedder(CountingEmbedder):
    """Embeds the first `ok_batches` batches, then raises, like a model crash."""

    def __init__(self, ok_batches: int) -> None:
        super().__init__()
        self.ok_batches = ok_batches

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.ok_batches == 0:
            raise RuntimeError("onnxruntime: out of memory")
        self.ok_batches -= 1
        return super().embed(texts)


async def test_an_embed_failure_makes_the_run_partial_and_the_next_run_resumes(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    from app.ingest.embed import BATCH_SIZE

    total = BATCH_SIZE * 3
    adapters["greenhouse"].boards = {"acme": [raw(str(i)) for i in range(total)]}

    first = await ingest(adapters, FailingEmbedder(ok_batches=1), T0)

    run = first.sources["greenhouse"]
    assert run.status == "partial"
    assert (run.new, run.embedded, run.embed_pending) == (total, BATCH_SIZE, total - BATCH_SIZE)
    assert run.error is not None
    assert f"embed: {total - BATCH_SIZE} jobs still without an embedding" in run.error
    assert "embed: RuntimeError('onnxruntime: out of memory')" in run.error
    assert first.errors == ["embed: RuntimeError('onnxruntime: out of memory')"]
    stored = (await session.scalars(select(IngestRun))).one()
    assert (stored.status, stored.embedded, stored.embed_pending) == (
        "partial",
        BATCH_SIZE,
        total - BATCH_SIZE,
    )
    # The batch that succeeded was committed before the failure.
    embedded_now = sum(1 for j in (await jobs(session)).values() if j.embedding is not None)
    assert embedded_now == BATCH_SIZE

    embedder = CountingEmbedder()
    second = await ingest(adapters, embedder, T0 + timedelta(hours=12))
    assert second.embedded == total - BATCH_SIZE  # only what was left
    assert len(embedder.embedded) == total - BATCH_SIZE
    assert second.sources["greenhouse"].status == "succeeded"
    assert second.sources["greenhouse"].embed_pending == 0


async def test_a_store_failure_fails_that_source_and_the_others_still_run(
    adapters: dict[str, ScriptedAdapter],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingest.store import upsert_jobs as real_upsert

    async def broken_for_lever(session: AsyncSession, jobs: Any, now: datetime) -> Any:
        if jobs and jobs[0][0].source == "lever":
            raise RuntimeError("disk full")
        return await real_upsert(session, jobs, now)

    monkeypatch.setattr("app.ingest.runner.upsert_jobs", broken_for_lever)
    companies = [*COMPANIES, CompanyEntry("Initech", "lever", "initech", ("saas",))]
    adapters["greenhouse"].boards = {"acme": [raw("1")]}
    adapters["lever"].boards = {"initech": [raw("l1", source="lever", company_name="Initech")]}

    async with httpx.AsyncClient() as http:
        summary = await run_ingest(
            SessionLocal,
            http,
            CountingEmbedder(),
            companies,
            get_settings(),
            sources=("greenhouse", "lever"),
            adapters=adapters,
            now=T0,
        )

    lever = summary.sources["lever"]
    assert lever.status == "failed"
    assert lever.error == "store: RuntimeError('disk full')"
    assert summary.sources["greenhouse"].status == "succeeded"
    assert set(await jobs(session)) == {"1"}
    rows = {r.source: r for r in await session.scalars(select(IngestRun))}
    assert rows["lever"].status == "failed" and rows["lever"].finished_at is not None


async def test_a_run_left_running_by_a_dead_process_is_marked_failed(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    import uuid

    dead = IngestRun(
        run_id=uuid.uuid4(),
        source="greenhouse",
        started_at=T0 - timedelta(hours=7),
        status="running",
        boards_ok=0,
        boards_failed=0,
        fetched=0,
        new=0,
        updated=0,
        unchanged=0,
        expired=0,
        skipped=0,
        failures=[],
    )
    recent = IngestRun(
        run_id=uuid.uuid4(),
        source="lever",
        started_at=T0 - timedelta(minutes=5),
        status="running",
        boards_ok=0,
        boards_failed=0,
        fetched=0,
        new=0,
        updated=0,
        unchanged=0,
        expired=0,
        skipped=0,
        failures=[],
    )
    session.add_all([dead, recent])
    await session.commit()

    await ingest(adapters, CountingEmbedder(), T0)

    session.expire_all()
    await session.refresh(dead)
    await session.refresh(recent)
    assert dead.status == "failed"
    assert dead.error == "interrupted: the run stopped without recording completion"
    assert recent.status == "running"  # could still be in progress elsewhere


async def test_a_source_with_no_configured_boards_is_skipped_not_failed(
    session: AsyncSession,
) -> None:
    from app.ingest.runner import ADAPTERS

    async with httpx.AsyncClient() as http:
        summary = await run_ingest(
            SessionLocal,
            http,
            CountingEmbedder(),
            COMPANIES,
            get_settings(),
            sources=("workable",),
            adapters={"workable": ADAPTERS["workable"]},
            now=T0,
        )
    run = summary.sources["workable"]
    assert (run.status, run.note) == ("skipped", "no boards configured for this source")
