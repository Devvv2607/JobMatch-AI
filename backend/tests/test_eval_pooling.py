"""Pool selection (app/eval/pooling.py) and the judge's spread sample, on hand-made
rankings: order, stratification caps, relaxation, depth."""

from app.eval.cli import spread_sample, token_report
from app.eval.pairs import EvalPair, JobCard, JudgeRecord
from app.eval.pooling import JobFacts, candidates, select_pool


def facts(**by_id: tuple[str, str, str]) -> dict[str, JobFacts]:
    return {k: JobFacts(*v) for k, v in by_id.items()}


EMPLOYER = ("greenhouse", "full_time", "employer")


def test_every_variants_rank_1_comes_before_any_rank_2() -> None:
    rankings = {"query:bm25": ["a", "b"], "query:vector": ["c", "d"], "profile:fused": ["e"]}
    f = facts(**{k: EMPLOYER for k in "abcde"})
    chosen = [c.job_id for c, _ in select_pool(rankings, f, per_profile=4)]
    assert set(chosen[:3]) == {"a", "c", "e"}
    assert chosen[3] in {"b", "d"}


def test_a_job_several_variants_rank_high_goes_first_among_equals() -> None:
    rankings = {"v1": ["a", "x"], "v2": ["b", "x"], "v3": ["c", "x"]}
    f = facts(**{k: EMPLOYER for k in "abcx"})
    chosen = [c.job_id for c, _ in select_pool(rankings, f, per_profile=4)]
    assert chosen[3] == "x"
    assert candidates(rankings)["x"].variants == {"v1": 2, "v2": 2, "v3": 2}


def test_caps_on_source_gigs_and_agencies_then_relaxed_only_if_short() -> None:
    ids = [f"h{i}" for i in range(8)] + ["g1", "g2", "a1", "a2", "e1"]
    rankings = {"v": ids}
    f = facts(
        **{f"h{i}": ("himalayas", "full_time", "employer") for i in range(8)},
        g1=("greenhouse", "freelance_gig", "employer"),
        g2=("greenhouse", "freelance_gig", "employer"),
        a1=("adzuna", "full_time", "staffing_agency"),
        a2=("adzuna", "full_time", "staffing_agency"),
        e1=EMPLOYER,
    )
    chosen = select_pool(rankings, f, per_profile=8, max_gig=1, max_agency=1)
    picked = [c.job_id for c, _ in chosen]
    # At most half (4) from Himalayas, 1 gig, 1 agency within the caps; then the caps
    # are relaxed in rank order to reach 8, and those are marked.
    within = [c.job_id for c, over in chosen if not over]
    assert within == ["h0", "h1", "h2", "h3", "g1", "a1", "e1"]
    assert picked[7] == "h4"
    assert [over for _, over in chosen].count(True) == 1


def test_jobs_outside_the_snapshot_are_never_pooled() -> None:
    chosen = select_pool({"v": ["gone", "a"]}, facts(a=EMPLOYER), per_profile=5)
    assert [c.job_id for c, _ in chosen] == ["a"]


def test_deeper_ranks_fill_a_short_pool() -> None:
    rankings = {"v": [f"j{i}" for i in range(15)]}
    f = facts(**{f"j{i}": EMPLOYER for i in range(15)})
    chosen = select_pool(rankings, f, per_profile=12, depth=10)
    assert [c.job_id for c, _ in chosen] == [f"j{i}" for i in range(12)]


def card(job_id: str) -> JobCard:
    return JobCard(
        job_id=job_id,
        title="t",
        company="c",
        source="greenhouse",
        location="",
        eligibility="worldwide",
        workplace="remote",
        employment="full_time",
        poster="employer",
        description="",
    )


def test_spread_sample_takes_one_profile_at_a_time() -> None:
    pairs = [
        EvalPair(pair_id=f"{p}:{j}", profile_id=p, job=card(j))
        for p in ("p01", "p02", "p03")
        for j in ("a", "b", "c")
    ]
    picked = spread_sample(pairs, 5, seed=1)
    profiles = [p.profile_id for p in picked]
    assert len(picked) == 5
    assert sorted(set(profiles[:3])) == ["p01", "p02", "p03"]
    assert spread_sample(pairs, 5, seed=1) == picked  # seeded


def test_token_report_uses_measured_uncached_calls() -> None:
    def rec(pid: str, prompt: int | None, cached: bool = False) -> JudgeRecord:
        return JudgeRecord(
            pair_id=pid,
            label=2,
            reason="fine",
            confidence="high",
            provider="groq",
            model="m",
            prompt="eval_judge/v1",
            cached=cached,
            prompt_tokens=prompt,
            completion_tokens=None if prompt is None else 100,
        )

    report = token_report([rec("a", 900), rec("b", 1100), rec("c", 5000, cached=True)])
    assert "2 judged calls: tokens per pair mean 1100 (prompt 1000, completion 100)" in report
    assert token_report([rec("a", None)]) == "no token counts recorded"


def test_agreement_counts_only_blind_pairs_both_judges_graded() -> None:
    from app.eval.agreement import agreement_report

    blind = ["a", "b", "c", "d"]
    judges = {
        "gemini": {"a": 3, "b": 0, "c": 2, "d": 1, "outside": 0},
        "groq": {"a": 2, "b": 0},
        "cowork": {"a": 3, "b": 0, "c": 2, "outside": 3},
    }
    rows = {(p["a"], p["b"]): p for p in agreement_report(blind, judges)["pairwise"]}
    assert rows[("gemini", "cowork")]["n"] == 3
    assert rows[("gemini", "cowork")]["weighted_kappa"] == 1.0
    assert rows[("gemini", "groq")]["n"] == 2
    assert rows[("gemini", "groq")]["exact"] == 0.5
    assert rows[("groq", "cowork")]["n"] == 2
