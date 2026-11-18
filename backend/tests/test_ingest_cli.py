"""The ingestion commands and the worker job, with scripted adapters and embedder."""

import json
from typing import Any

import pytest

from app.ingest import cli
from app.ingest.companies import CompanyEntry
from app.ingest.sources.base import SourceError
from app.worker import ingest_jobs
from tests.test_ingest_pipeline import (
    COMPANIES,
    CountingEmbedder,
    ScriptedAdapter,
    raw,
)


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> dict[str, ScriptedAdapter]:
    adapters = {s: ScriptedAdapter(s) for s in ("greenhouse", "lever", "ashby", "remotive")}
    adapters["greenhouse"].boards = {
        "acme": [
            raw("in-1"),  # Bengaluru: eligible for India
            raw("us-1", locations=["Austin, TX"]),  # ineligible
            raw("ww-1", locations=["Worldwide"], workplace="remote"),  # eligible
            raw("un-1", locations=["Remote"], workplace="remote"),  # unknown
            raw(
                "dup",
                title="Engineer in-1",
                description_html="<p>Role in-1. Python and PostgreSQL.</p>",
            ),
        ],
        "globex": SourceError("board not found (HTTP 404)"),
    }
    monkeypatch.setattr("app.ingest.runner.ADAPTERS", adapters)
    monkeypatch.setattr("app.ingest.cli.ADAPTERS", adapters)
    monkeypatch.setattr("app.ingest.cli.load_companies", lambda: COMPANIES)
    monkeypatch.setattr("app.ingest.companies.load_companies", lambda: COMPANIES)
    monkeypatch.setattr("app.ml.embedder.OnnxEmbedder", lambda *a, **k: CountingEmbedder())
    return adapters


async def test_run_then_report(
    scripted: dict[str, ScriptedAdapter], capsys: pytest.CaptureFixture[str]
) -> None:
    assert await cli.cmd_run(["greenhouse"]) == 0
    run = json.loads(capsys.readouterr().out)
    assert run["sources"]["greenhouse"]["new"] == 5
    assert run["sources"]["greenhouse"]["boards_failed"] == 1
    assert run["embedded"] == 5

    assert await cli.cmd_report("in") == 0
    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert report["country"] == "IN"
    assert report["totals"][0] == {"active": 5, "unique_active": 4, "expired": 0, "embedded": 5}
    eligibility = {row["eligibility"]: row["jobs"] for row in report["eligibility"]}
    assert eligibility == {"eligible": 2, "ineligible": 1, "unknown": 1}
    rules = {row["rule"]: row["jobs"] for row in report["eligibility_rules"]}
    assert rules["location:greenhouse.location:worldwide"] == 1
    assert rules["none"] == 1
    assert report["unknown_location_phrases"] == [{"location": "Remote", "jobs": 1}]
    assert report["duplicates"] == [{"reason": "content_hash", "jobs": 1}]
    (last_run,) = report["last_run"]
    assert last_run["failures"] == [{"board": "globex", "error": "board not found (HTTP 404)"}]


async def test_check_boards_reports_dead_and_empty_boards(
    scripted: dict[str, ScriptedAdapter],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    companies = [*COMPANIES, CompanyEntry("Initech", "lever", "initech", ("saas",))]
    monkeypatch.setattr("app.ingest.cli.load_companies", lambda: companies)
    monkeypatch.setattr("app.ingest.cli.asyncio.sleep", _no_sleep)

    assert await cli.cmd_check_boards() == 1
    out = capsys.readouterr().out
    assert "acme             live     5 postings" in out
    assert "globex           DEAD  board not found (HTTP 404)" in out
    assert "initech          EMPTY (no postings)" in out
    assert "2 dead or empty of 3" in out


async def test_check_boards_passes_when_every_board_is_live(
    scripted: dict[str, ScriptedAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted["greenhouse"].boards["globex"] = [raw("g", company_name="Globex")]
    monkeypatch.setattr("app.ingest.cli.asyncio.sleep", _no_sleep)
    assert await cli.cmd_check_boards() == 0


def test_main_rejects_unknown_sources_before_doing_anything() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["run", "--sources", "greenhouse,monster"])
    assert excinfo.value.code == 2


async def test_worker_ingest_job_runs_every_source_and_reuses_the_embedder(
    scripted: dict[str, ScriptedAdapter],
) -> None:
    ctx: dict[str, Any] = {}
    first = await ingest_jobs(ctx)
    embedder = ctx["embedder"]
    assert first["embedded"] == 5
    # Every configured source ran: greenhouse boards and the Remotive feed.
    assert scripted["greenhouse"].calls == 2 and scripted["remotive"].calls == 1

    second = await ingest_jobs(ctx)
    assert ctx["embedder"] is embedder  # loaded once per worker process
    assert second["embedded"] == 0


async def _no_sleep(_: float) -> None:
    return None
