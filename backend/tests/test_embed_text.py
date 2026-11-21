"""The embedding input: boilerplate stripping, the job card, the recipe version, and the
store step's memory-light loading."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import engine
from app.ingest import embed as embed_module
from app.ingest.boilerplate import boilerplate_keys, paragraphs, strip_boilerplate
from app.ingest.embed import embed_pending, job_card, prepare_embedding_input
from app.models import Job
from tests.test_ingest_pipeline import T0, CountingEmbedder, ScriptedAdapter, ingest, jobs, raw

ABOUT = "About Acme\n\nAcme builds rockets for everyone."
EEO = "Acme is an equal opportunity employer."


def described(role: str) -> str:
    return f"{ABOUT}\n\n{role}\n\n- Requirement for {role}\n\n{EEO}"


# --- the rule ---------------------------------------------------------------------------


def test_paragraphs_split_on_blank_lines_and_drop_empties() -> None:
    assert paragraphs("One\nstill one\n\n\n  Two  \n\n \n- three") == [
        "One\nstill one",
        "Two",
        "- three",
    ]


def test_a_paragraph_in_30_percent_of_postings_is_boilerplate_and_below_is_not() -> None:
    # 10 distinct descriptions: "shared-3" is in 3 (30%), "shared-2" in 2 (20%).
    descriptions = [
        "\n\n".join(
            [f"Role {i}"] + (["shared-3"] if i < 3 else []) + (["shared-2"] if i < 2 else [])
        )
        for i in range(10)
    ]
    keys = boilerplate_keys(descriptions, min_share=0.3, min_postings=5)
    assert "shared 3" in keys
    assert "shared 2" not in keys
    assert not any(k.startswith("role") for k in keys)


def test_small_companies_keep_everything() -> None:
    descriptions = [described(f"Role {i}") for i in range(4)]
    assert boilerplate_keys(descriptions, min_share=0.3, min_postings=5) == frozenset()


def test_identical_descriptions_count_once() -> None:
    """One role posted in many cities must not make its own text look like boilerplate:
    6 copies of one description plus 4 others is 5 distinct descriptions, and the copied
    role's paragraphs occur in 1 of 5 (20%)."""
    copies = [described("Staff ML Engineer")] * 6
    others = [described(f"Role {i}") for i in range(4)]
    keys = boilerplate_keys(copies + others, min_share=0.3, min_postings=5)
    assert "staff ml engineer" not in keys
    assert "about acme" in keys


def test_matching_is_on_normalised_text() -> None:
    descriptions = [
        f"Role {i}\n\n" + ("ACME is an Equal-Opportunity employer!" if i % 2 else EEO)
        for i in range(6)
    ]
    keys = boilerplate_keys(descriptions, min_share=0.3, min_postings=5)
    stripped = strip_boilerplate(descriptions[1], keys)
    assert stripped == "Role 1"


def test_stripping_keeps_the_rest_in_order_and_drops_separator_paragraphs() -> None:
    keys = boilerplate_keys(
        [described(f"Role {i}") for i in range(5)], min_share=0.3, min_postings=5
    )
    text = described("Build the data platform") + "\n\n---\n\nApply now"
    assert strip_boilerplate(text, keys) == (
        "Build the data platform\n\n- Requirement for Build the data platform\n\nApply now"
    )


def test_job_card_puts_the_structured_header_first() -> None:
    card = job_card("ML Engineer", "senior", ["Python", "PyTorch"], "Bengaluru, India", "Body")
    assert card == (
        "ML Engineer\nLevel: senior\nSkills: Python, PyTorch\nLocation: Bengaluru, India\nBody"
    )
    assert job_card("ML Engineer", "mid", [], "", "") == "ML Engineer\nLevel: mid"


# --- in the pipeline --------------------------------------------------------------------


@pytest.fixture
def adapters() -> dict[str, ScriptedAdapter]:
    return {s: ScriptedAdapter(s) for s in ("greenhouse", "lever", "ashby", "remotive")}


@pytest.fixture
def acme_six(adapters: dict[str, ScriptedAdapter]) -> dict[str, ScriptedAdapter]:
    adapters["greenhouse"].boards = {
        "acme": [
            raw(str(i), title=f"Role {i}", description_html=f"<div>{_html(f'Role {i}')}</div>")
            for i in range(6)
        ]
    }
    return adapters


def _html(role: str) -> str:
    return (
        "<h2>About Acme</h2><p>Acme builds rockets for everyone.</p>"
        f"<p>{role}</p><ul><li>Requirement for {role}</li></ul><p>{EEO}</p>"
    )


async def test_the_embedded_text_has_no_company_boilerplate(
    acme_six: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    embedder = CountingEmbedder()
    await ingest(acme_six, embedder, T0)

    row = (await jobs(session))["3"]
    assert row.search_text == "Role 3\n\n- Requirement for Role 3"
    assert "About Acme" in row.description  # the stored description is untouched
    card = next(c for c in embedder.embedded if c.startswith("Role 3\n"))
    assert "rockets" not in card and EEO not in card
    assert "Location: Bengaluru, India" in card and "Requirement for Role 3" in card


async def test_a_recipe_version_change_re_embeds_every_job_once(
    acme_six: dict[str, ScriptedAdapter],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedder = CountingEmbedder()
    await ingest(acme_six, embedder, T0)
    assert len(embedder.embedded) == 6
    unchanged = await ingest(acme_six, embedder, T0 + timedelta(hours=12))
    assert unchanged.embedded == 0

    monkeypatch.setattr(embed_module, "EMBED_TEXT_VERSION", embed_module.EMBED_TEXT_VERSION + 1)
    bumped = await ingest(acme_six, embedder, T0 + timedelta(days=1))
    assert bumped.embedded == 6
    again = await ingest(acme_six, embedder, T0 + timedelta(days=2))
    assert again.embedded == 0
    assert all(j.embedded_hash == j.embed_input_hash for j in (await jobs(session)).values())


async def test_a_boilerplate_change_re_embeds_only_the_jobs_whose_text_changed(
    acme_six: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    embedder = CountingEmbedder()
    await ingest(acme_six, embedder, T0)

    # Two postings gain a shared paragraph: 2 of 6 is 33%, so it is boilerplate and
    # stripped. Their content changed, but the embedded text did not: nothing to do.
    extra = "<p>We sponsor visas.</p>"

    def board(count: int) -> list[Any]:
        return [
            raw(
                str(i),
                title=f"Role {i}",
                description_html=f"<div>{_html(f'Role {i}')}{extra if i < 2 else ''}</div>",
            )
            for i in range(count)
        ]

    acme_six["greenhouse"].boards["acme"] = board(6)
    summary = await ingest(acme_six, embedder, T0 + timedelta(hours=12))
    assert summary.sources["greenhouse"].updated == 2
    assert summary.embedded == 0
    assert "visas" not in ((await jobs(session))["0"].search_text or "")

    # Four more postings: the paragraph is now in 2 of 10 (20%), no longer boilerplate.
    # Jobs 0 and 1 are re-embedded (their content did not change) along with the 4 new.
    acme_six["greenhouse"].boards["acme"] = board(10)
    before = len(embedder.embedded)
    summary = await ingest(acme_six, embedder, T0 + timedelta(days=1))
    assert summary.sources["greenhouse"].new == 4
    assert summary.embedded == 6
    re_embedded = [c.split("\n", 1)[0] for c in embedder.embedded[before:]]
    assert sorted(re_embedded) == sorted(["Role 0", "Role 1", *(f"Role {i}" for i in range(6, 10))])
    assert "visas" in ((await jobs(session))["0"].search_text or "")


async def test_prepare_skips_expired_jobs(
    acme_six: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    await ingest(acme_six, CountingEmbedder(), T0)
    await session.execute(
        update(Job).where(Job.source_id == "0").values(status="expired", search_text=None)
    )
    await session.commit()
    changed = await prepare_embedding_input(session, min_share=0.3, min_postings=5)
    assert changed == 0
    assert (await jobs(session))["0"].search_text is None
    assert await embed_pending(session, CountingEmbedder()) == 0


# --- store step -------------------------------------------------------------------------


@pytest.fixture
def statements() -> Iterator[list[str]]:
    seen: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine.sync_engine, "before_cursor_execute", record)


async def test_the_store_step_never_loads_descriptions_or_embeddings(
    acme_six: dict[str, ScriptedAdapter],
    statements: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingest.store import upsert_jobs

    embedder = CountingEmbedder()
    await ingest(acme_six, embedder, T0)

    loaded: list[str] = []

    async def watched(*args: Any) -> Any:
        start = len(statements)
        result = await upsert_jobs(*args)
        loaded.extend(s for s in statements[start:] if s.lstrip().upper().startswith("SELECT"))
        return result

    monkeypatch.setattr("app.ingest.runner.upsert_jobs", watched)
    await ingest(acme_six, embedder, T0 + timedelta(hours=12))
    assert loaded, "the store step should look up existing jobs"
    for sql in loaded:
        assert "jobs.embedding" not in sql and "jobs.description" not in sql, sql


async def test_rule_derived_fields_are_refreshed_on_unchanged_postings(
    adapters: dict[str, ScriptedAdapter], session: AsyncSession
) -> None:
    """A rule change (here simulated by corrupting the stored eligibility) reaches a job
    on the next run even though its content hash did not change."""
    adapters["greenhouse"].boards = {"acme": [raw("1")]}
    embedder = CountingEmbedder()
    await ingest(adapters, embedder, T0)
    await session.execute(
        update(Job).values(
            eligibility_scope="unknown", work_countries=[], eligibility_source="none"
        )
    )
    await session.commit()

    summary = await ingest(adapters, embedder, T0 + timedelta(hours=12))
    row = (await jobs(session))["1"]
    assert summary.sources["greenhouse"].unchanged == 1
    assert (row.eligibility_scope, row.work_countries) == ("listed", ["IN"])
    assert row.content_changed_at == T0  # not treated as a content change
    assert summary.embedded == 0
    ids = (await session.scalars(select(Job.id))).all()
    assert len(ids) == 1


async def test_every_batch_is_embedded_on_the_same_thread(
    adapters: dict[str, ScriptedAdapter],
) -> None:
    """One thread for the model keeps it to one malloc arena (see embed._EMBED_THREAD)."""
    import asyncio
    import threading

    from app.ingest.embed import BATCH_SIZE

    class ThreadRecorder(CountingEmbedder):
        def __init__(self) -> None:
            super().__init__()
            self.threads: set[int] = set()

        def embed(self, texts: list[str]) -> list[list[float]]:
            self.threads.add(threading.get_ident())
            return super().embed(texts)

    loop = asyncio.get_running_loop()
    # Warm the default executor with several threads, as DNS lookups do in a real run.
    await asyncio.gather(
        *(loop.run_in_executor(None, threading.Event().wait, 0.05) for _ in range(6))
    )
    adapters["greenhouse"].boards = {"acme": [raw(str(i)) for i in range(BATCH_SIZE * 4)]}
    embedder = ThreadRecorder()
    await ingest(adapters, embedder, T0)
    assert len(embedder.embedded) == BATCH_SIZE * 4
    assert len(embedder.threads) == 1
