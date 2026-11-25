"""The labelling tool's store and order (app/eval/labels.py) and its HTTP API
(app/eval/labelling.py), on a small throwaway set in a temporary folder."""

import json
from collections import Counter
from pathlib import Path

import httpx
import pytest

from app.eval.labelling import create_app
from app.eval.labels import LabelSession, label_sources, stratified_sample, suggested_order
from app.eval.pairs import EvalPair, JobCard, JudgeRecord, load_pairs, pair_id, write_jsonl
from app.eval.profiles import load_profiles

PROFILES = load_profiles()


def card(i: int, source: str, employment: str = "full_time", poster: str = "employer") -> JobCard:
    return JobCard(
        job_id=f"job{i}",
        title=f"Engineer {i}",
        company="Acme",
        source=source,
        location="Pune",
        eligibility="IN",
        workplace="hybrid",
        employment=employment,
        poster=poster,
        description="Build things.",
    )


def make_pairs(n: int = 12) -> list[EvalPair]:
    sources = ["greenhouse", "himalayas", "ashby", "adzuna"]
    out = []
    for i in range(n):
        c = card(i, sources[i % 4], "freelance_gig" if i % 5 == 0 else "full_time")
        out.append(EvalPair(pair_id=pair_id("p01", c.job_id), profile_id="p01", job=c))
    return out


def judge_for(pairs: list[EvalPair]) -> dict[str, JudgeRecord]:
    confidences = ["high", "low", "medium"]
    return {
        p.pair_id: JudgeRecord(
            pair_id=p.pair_id,
            label=i % 4,
            reason="r",
            confidence=confidences[i % 3],
            provider="stub",
            model="m",
            prompt="eval_judge/v1",
        )
        for i, p in enumerate(pairs)
    }


def lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def test_stratified_sample_covers_strata_and_is_reproducible() -> None:
    pairs = make_pairs(40)
    chosen = stratified_sample(pairs, 10, seed=3)
    assert len(chosen) == len(set(chosen)) == 10
    assert chosen == stratified_sample(pairs, 10, seed=3)
    by_id = {p.pair_id: p for p in pairs}
    strata = {(by_id[c].job.source, by_id[c].job.employment) for c in chosen}
    all_strata = {(p.job.source, p.job.employment) for p in pairs}
    assert strata == all_strata  # 8 strata, 10 slots: every stratum is represented
    assert stratified_sample(pairs, 100, seed=3).__len__() == 40


def test_suggested_order_puts_uncertain_and_boundary_grades_first() -> None:
    pairs = make_pairs(12)
    judge = judge_for(pairs)
    del judge[pairs[0].pair_id]  # one pair not judged yet
    order = suggested_order(pairs, set(), judge, seed=1)
    conf = [judge[pid].confidence if pid in judge else "none" for pid in order]
    rank = {"low": 0, "medium": 1, "high": 2, "none": 3}
    assert [rank[c] for c in conf] == sorted(rank[c] for c in conf)
    assert order[-1] == pairs[0].pair_id
    lows = [pid for pid in order if pid in judge and judge[pid].confidence == "low"]
    grades = [judge[pid].label for pid in lows]
    boundary = [g in (1, 2) for g in grades]
    assert boundary == sorted(boundary, reverse=True)  # grades 1-2 before 0/3


def session(tmp_path: Path, n: int = 8, blind: int = 3) -> LabelSession:
    pairs = make_pairs(n)
    write_jsonl(tmp_path / "pairs.jsonl", pairs)
    return LabelSession(tmp_path, pairs, judge_for(pairs), blind_size=blind)


def test_blind_phase_first_without_suggestions_and_every_label_saved(tmp_path: Path) -> None:
    s = session(tmp_path)
    for i in range(3):
        pid = s.current()
        assert pid in s.plan.blind
        assert not s.shows_suggestion(pid)
        s.label(pid, i)
        assert len(lines(tmp_path / "human.jsonl")) == i + 1  # on disk before the next
    pid = s.current()
    assert pid in s.plan.suggested and s.shows_suggestion(pid)
    saved = lines(tmp_path / "human.jsonl")
    assert [e["phase"] for e in saved] == ["blind"] * 3
    assert not any(e["shown_suggestion"] for e in saved)


def test_skipped_blind_pairs_return_before_any_suggestion(tmp_path: Path) -> None:
    s = session(tmp_path)
    first = s.current()
    s.skip(first)  # type: ignore[arg-type]
    s.label(s.current(), 2)  # type: ignore[arg-type]
    s.label(s.current(), 2)  # type: ignore[arg-type]
    assert s.current() == first  # back, still blind
    assert not s.shows_suggestion(first)  # type: ignore[arg-type]
    s.skip(first)  # type: ignore[arg-type]
    assert s.current() == first  # the only blind pair left: skipping again keeps it
    s.label(first, 1)  # type: ignore[arg-type]
    assert s.blind_done()


def test_skipped_pairs_rotate_oldest_skip_first(tmp_path: Path) -> None:
    s = session(tmp_path, n=8, blind=3)
    a = s.current()
    s.skip(a)  # type: ignore[arg-type]
    b = s.current()
    s.skip(b)  # type: ignore[arg-type]
    c = s.current()
    s.skip(c)  # type: ignore[arg-type]
    assert s.current() == a  # all three skipped: the oldest skip first
    s.skip(a)  # type: ignore[arg-type]
    assert s.current() == b


def test_undo_reopens_the_last_pair_and_is_logged(tmp_path: Path) -> None:
    s = session(tmp_path)
    first = s.current()
    s.label(first, 3)  # type: ignore[arg-type]
    second = s.current()
    assert s.undo() == first
    assert s.current() == first
    assert first not in s.state.entries
    s.label(first, 1)  # type: ignore[arg-type]
    assert s.state.entries[first].label == 1  # type: ignore[index]
    assert s.current() == second
    assert [e["event"] for e in lines(tmp_path / "human.jsonl")] == ["label", "undo", "label"]
    assert s.undo() == first and s.undo() is None  # nothing left to undo


def test_resume_replays_the_log_exactly(tmp_path: Path) -> None:
    s = session(tmp_path, n=8, blind=3)
    for value in (0, 1, 2, 3):
        s.label(s.current(), value)  # type: ignore[arg-type]
    s.skip(s.current())  # type: ignore[arg-type]
    s.undo()
    s.label(s.current(), 2)  # type: ignore[arg-type]
    plan_before = (tmp_path / "plan.json").read_text(encoding="utf-8")
    again = LabelSession(tmp_path, load_pairs(tmp_path / "pairs.jsonl"), s.judge, blind_size=3)
    assert (tmp_path / "plan.json").read_text(encoding="utf-8") == plan_before  # same order
    assert again.state.entries == s.state.entries
    assert again.current() == s.current()
    assert again.progress() == s.progress()


def test_a_label_for_another_pair_is_refused(tmp_path: Path) -> None:
    s = session(tmp_path)
    other = next(pid for pid in s.pairs if pid != s.current())
    with pytest.raises(ValueError):
        s.label(other, 2)
    assert not (tmp_path / "human.jsonl").exists()


def test_label_sources_human_first_then_llm_only(tmp_path: Path) -> None:
    s = session(tmp_path, n=6, blind=2)
    for value in (3, 0):
        s.label(s.current(), value)  # type: ignore[arg-type]
    s.label(s.current(), 2)  # type: ignore[arg-type]  # second phase, suggestion shown
    final = label_sources(list(s.pairs.values()), s.judge, tmp_path / "human.jsonl")
    sources = Counter(src for _, src in final.values())
    assert sources == {"human_blind": 2, "human_with_suggestion": 1, "llm_only": 3}


async def test_the_page_and_api_label_skip_and_undo(tmp_path: Path) -> None:
    s = session(tmp_path)
    app = create_app(s, PROFILES)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://label"
    ) as client:
        page = await client.get("/")
        assert page.status_code == 200 and "keydown" in page.text
        state = (await client.get("/api/state")).json()
        assert state["phase"] == "blind" and state["suggestion"] is None
        assert state["profile"]["id"] == "p01" and "Rubric" in state["rubric"]
        first = state["pair_id"]
        state = (await client.post("/api/label", json={"pair_id": first, "label": 2})).json()
        assert state["progress"]["done"] == 1 and state["pair_id"] != first
        wrong = await client.post("/api/label", json={"pair_id": first, "label": 2})
        assert wrong.status_code == 409
        bad = await client.post("/api/label", json={"pair_id": state["pair_id"], "label": 7})
        assert bad.status_code == 422
        state = (await client.post("/api/skip", json={"pair_id": state["pair_id"]})).json()
        assert state["progress"]["skipped"] == 1
        state = (await client.post("/api/undo")).json()
        assert state["progress"]["skipped"] == 0
    assert [e["event"] for e in lines(tmp_path / "human.jsonl")] == ["label", "skip", "undo"]
